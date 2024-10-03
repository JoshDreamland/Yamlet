import ast
import copy
import io
import pathlib
import ruamel.yaml
import sys
import token
import tokenize

class YamletOptions:
  Error = ['error']
  def __init__(self, import_resolver=None, missing_name_value=Error,
               functions={}):
    self.import_resolver = import_resolver or str
    self.missing_name_value = missing_name_value
    self.functions = functions


class GclDict(dict):
  def __init__(self, *args, gcl_parent, gcl_opts, yaml_point, **kwargs):
    super().__init__(*args, **kwargs)
    self._gcl_parent_ = gcl_parent
    self._gcl_opts_ = gcl_opts
    self._yaml_point_ = yaml_point

  def _resolvekv(self, k, v, ectx=None):
    if isinstance(v, DeferredValue):
      r = v._gcl_resolve_(ectx or
          _EvalContext(self, self._gcl_opts_, self._yaml_point_,
                       name=f'Lookup of `{k}` in this scope'))
      # XXX: This is a nice optimization, but breaks accessing templates before
      # their derived types. We need to let the caching handle it for that case.
      # self.__setitem__(k, r)
      return r
    else:
      return v

  def __getitem__(self, key):
    try:
      return self._resolvekv(key, super().__getitem__(key))
    except ExceptionWithYamletTrace as e: exception_during_access = e.rewind()
    raise exception_during_access

  def items(self):
    return ((k, self._resolvekv(k, v)) for k, v in super().items())

  def values(self):
    return (v for _, v in self.items())

  def _gcl_merge_(self, other):
    if not isinstance(other, GclDict):
      raise TypeError('Expected GclDict to merge.')
    for k, v in other._gcl_noresolve_items_():
      if isinstance(v, GclDict):
        v1 = super().setdefault(k, v)
        if v1 is not v:
          v1._gcl_merge_(v)
          v = v1
        else:
          v = v._gcl_clone_(self)
          super().__setitem__(k, v)
        assert v._gcl_parent_ is self
      elif isinstance(v, DeferredValue):
        super().__setitem__(k, v._gcl_clone_deferred_())
      else:
        super().__setitem__(k, v)

  def _gcl_clone_(self, new_parent):
    '''Clones GclDicts recursively, updating parents.'''
    res = GclDict(gcl_parent=new_parent, gcl_opts=self._gcl_opts_,
                  yaml_point=self._yaml_point_)
    for k, v in self._gcl_noresolve_items_():
      if isinstance(v, GclDict): v = v._gcl_clone_(res)
      res.__setitem__(k, v)
    return res

  def _gcl_clone_unresolved_(self):
    if not self._gcl_has_unresolved_(): return self
    def maybe_clone(v):
      if isinstance(v, GclDict): return v._gcl_clone_unresolved_()
      if isinstance(v, DeferredValue):
        _DebugPrint(f'Clone {type(v).__name__} `{v._gcl_construct_}`')
        return copy.copy(v)
      return v
    return GclDict({
        k: maybe_clone(v) for k, v in self._gcl_noresolve_items_()},
        gcl_parent=self._gcl_parent_, gcl_opts=self._gcl_opts_,
        yaml_point=self._yaml_point_)

  def _gcl_has_unresolved_(self):
    for k, v in self._gcl_noresolve_items_():
      if isinstance(v, DeferredValue): return True
      if isinstance(v, GclDict) and v._gcl_has_unresolved_(): return True
    return False

  def _gcl_noresolve_values_(self): return super().values()
  def _gcl_noresolve_items_(self): return super().items()
  def _gcl_traceable_get_(self, key, ectx):
    return self._resolvekv(key, super().__getitem__(key), ectx)


class YamletLoader(ruamel.yaml.YAML):
  def __init__(self, *args, gcl_opts, **kwargs):
    super().__init__(*args, **kwargs)
    # Set custom dict type for base operations
    self.constructor.yaml_base_dict_type = GclDict
    self.representer.add_representer(GclDict, self.representer.represent_dict)

    def ConstructGclDict(loader, node):
      return GclDict(loader.construct_pairs(node), gcl_parent=None,
                     gcl_opts=gcl_opts,
                     yaml_point=YamlPoint(
                        start=node.start_mark, end=node.end_mark))

    # Override the constructor to always return our custom dict type
    self.constructor.add_constructor(
        ruamel.yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        ConstructGclDict)


class ExceptionWithYamletTrace(Exception):
  def __init__(self, ex_class, message):
    super().__init__(message)
    self.ex_class = ex_class
    self.traced_message = message
  def rewind(self):
    class YamletException(self.ex_class):
      def __init__(self, message, details):
        super().__init__(message)
        self.details = details
    return YamletException(self.traced_message, self)


class YamlPoint:
  def __init__(self, start, end):
    self.start = start
    self.end = end



class TraceItem(YamlPoint):
  def __init__(self, yaml_point, name):
    super().__init__(yaml_point.start, yaml_point.end)
    self.name = name


def _PrettyError(tace_item):
  if tace_item.name: return f'{tace_item.name}\n{tace_item.start}'
  return str(tace_item.start)


class _EvalContext:
  def __init__(self, scope, opts, yaml_point, name):
    self.scope = scope
    self.opts = opts
    if type(yaml_point) is list:
      self.trace = yaml_point
      assert name is None
    else:
      self.trace = [TraceItem(yaml_point, name)]
    self.evaluating = set()

  def AddObjectTrace(self, deferred_object, name):
    self.trace.append(TraceItem(deferred_object._yaml_point_, name))
    if deferred_object in self.evaluating:
      self.Raise(RecursionError, 'Dependency cycle in tuple values.')
    self.evaluating.add(deferred_object)

  def AddNamedTrace(self, yaml_point, name):
    self.trace.append(TraceItem(yaml_point, name))

  def FormatError(yaml_point, msg):
    return f'{yaml_point.start}\n{msg}'

  def Error(self, msg):
    return _EvalContext.FormatError(self.trace[-1], msg)

  def NewGclDict(self, *args, **kwargs):
    return GclDict(*args, **kwargs,
        gcl_parent=self.scope, gcl_opts=self.opts, yaml_point=self.trace[-1])

  def Duplicate(self):
    return _EvalContext(self.scope, self.opts, list(self.trace), name=None)

  def AtScope(self, scope):
    res = self.Duplicate()
    res.scope = scope
    return res

  def Raise(self, ex_class, message_sentence):
    raise ExceptionWithYamletTrace(ex_class,
        'An error occurred while evaluating a Yamlet expression:\n'
        + '\n'.join(_PrettyError(t) for t in self.trace)
        + f'\n{message_sentence} See above trace for details.')


class DeferredValue:
  def __init__(self, data, yaml_point):
    self._gcl_construct_ = data
    self._gcl_cache_ = None
    self._yaml_point_ = yaml_point
  def _gcl_resolve_(self, ectx):
    raise NotImplementedError('Abstract method Resolve.')
  def _gcl_clone_deferred_(self):
    res = copy.copy(self)
    res._gcl_cache_ = None
    return res


class ModuleToLoad(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      ectx.AddObjectTrace(self, f'Resolving import `{self._gcl_construct_}`')
      fn = _ResolveStringValue(self._gcl_construct_, ectx)
      fn = pathlib.Path(ectx.opts.import_resolver(fn))
      _DebugPrint(f'Load the following module: {fn}')
      if not fn.exists():
        if self._gcl_construct_ == fn:
          raise FileNotFoundError(f'Could not import YamlBcl file: {self.data}')
        raise FileNotFoundError(
            f'Could not import YamlBcl file: `{fn}`\n'
            f'As evaluated from this expression: `{self.data}`')
      loaded = self._gcl_loader_(fn)
      _DebugPrint(f'Loaded:\n{loaded}')
      self._gcl_cache_ = loaded
    return self._gcl_cache_


class StringToSubstitute(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      ectx.AddObjectTrace(self, f'Evaluating string `{self._gcl_construct_}`')
      self._gcl_cache_ = _ResolveStringValue(self._gcl_construct_, ectx)
    return self._gcl_cache_


class TupleListToComposite(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      ectx.AddObjectTrace(
          self, f'Compositing tuple list `{self._gcl_construct_}`')
      self._gcl_cache_ = _CompositeTuples(self._gcl_construct_, ectx)
    return self._gcl_cache_


class ExpressionToEvaluate(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      ectx.AddObjectTrace(
          self, f'Evaluating expression `{self._gcl_construct_}`')
      self._gcl_cache_ = _GclExprEval(self._gcl_construct_, ectx)
    return self._gcl_cache_


class GclLambda:
  def __init__(self, expr, yaml_point):
    self.yaml_point = yaml_point
    sep = expr.find(':')
    if sep < 0: raise ArgumentError(_EvalContext.FormatError(yaml_point,
        f'Lambda does not delimit arguments from expression: `{expr}`'))
    self.params = [x.strip() for x in expr[:sep].split(',')]
    self.expression = expr[sep+1:]
  def Callable(self, name, ectx):
    ectx2 = ectx.Duplicate()
    ectx2.AddNamedTrace(self.yaml_point, f'lambda `{name}`')
    params = self.params
    def LambdaEvaluator(*args, **kwargs):
      mapped_args = list(args)
      if len(mapped_args) > len(params):
        ectx.Raise(TypeError, f'Too many arguments to lambda; '
                              f'wanted {len(params)}, got {len(mapped_args)}.')
      while len(mapped_args) < len(params):
        p = params[len(mapped_args)]
        if p in kwargs:
          mapped_args.append(kwargs[p])
          del kwargs[p]
        else:
          ectx.Raise(TypeError, f'Missing argument `{p}` to lambda `{name}`')
      if kwargs: ectx.Raise(TypeError,
          f'Extra keyword arguments `{kwargs.keys()}` to lambda `{name}`')
      ectx2.scope = ectx2.NewGclDict({
          params[i]: mapped_args[i] for i in range(len(params))})
      return _GclExprEval(self.expression, ectx2)
    return LambdaEvaluator


def _DebugPrint(msg): pass #print(msg)
def _GclWarning(msg):
  print(msg, file=sys.stderr)


def DynamicScopeLoader(opts=YamletOptions()):
  loaded_modules = {}

  def LoadCachedFile(fn):
    fn = fn.resolve()
    if fn in loaded_modules:
      res = loaded_modules[fn]
      if res is None:
        raise RecursionError(f'Processing config `{fn}` results in recursion. '
                             'This isn\'t supposed to happen, as import loads '
                             'are deferred until name lookup.')
      return res
    loaded_modules[fn] = None
    with open(fn) as file: res = ProcessYamlGcl(file.read())
    loaded_modules[fn] = res
    return res

  def GclImport(loader, node):
    filename = loader.construct_scalar(node)
    res = ModuleToLoad(filename, YamlPoint(node.start_mark, node.end_mark))
    res._gcl_loader_ = LoadCachedFile
    return res

  def GclComposite(loader, node):
    marks = YamlPoint(node.start_mark, node.end_mark)
    if isinstance(node, ruamel.yaml.ScalarNode):
      return TupleListToComposite(loader.construct_scalar(node).split(), marks)
    if isinstance(node, ruamel.yaml.SequenceNode):
      return TupleListToComposite(loader.construct_sequence(node), marks)
    raise ArgumentError(f'Got unexpected node type: {repr(node)}')

  def GclStrFormat(loader, node):
    return StringToSubstitute(loader.construct_scalar(node),
                              YamlPoint(node.start_mark, node.end_mark))

  def GclExpression(loader, node):
    return ExpressionToEvaluate(
        node.value, YamlPoint(node.start_mark, node.end_mark))

  def GclLambdaC(loader, node):
    return GclLambda(
        node.value, YamlPoint(node.start_mark, node.end_mark))

  y = YamletLoader(gcl_opts=opts)
  y.constructor.add_constructor("!import", GclImport)
  y.constructor.add_constructor("!composite", GclComposite)
  y.constructor.add_constructor("!fmt", GclStrFormat)
  y.constructor.add_constructor("!expr", GclExpression)
  y.constructor.add_constructor("!lambda", GclLambdaC)

  def ProcessYamlGcl(ygcl):
    tup = y.load(ygcl)
    _RecursiveUpdateParents(tup, None, opts)
    return tup

  class Result():
    def load(self, filename):
      with open(filename) as fn: return self.loads(fn)
    def loads(self, yaml_gcl): return ProcessYamlGcl(yaml_gcl)
  return Result()


def _TokensCollide(t1, t2):
  if not t1: return False
  colliding_tokens = {token.NAME, token.NUMBER, token.STRING, token.OP}
  if t1.type not in colliding_tokens or t2.type not in colliding_tokens:
    return False
  if t1.type == token.STRING and t2.type == token.STRING: return False
  if t1.type == token.NAME and t2.type == token.OP:  return t2.string == '{'
  if t2.type == token.OP and t2.string not in '([{': return False
  if t1.type == token.OP and t1.string not in ')]}': return False
  return True


def _ParseIntoChunks(expr):
  tokens = tokenize.tokenize(io.BytesIO(expr.encode('utf-8')).readline)
  token_blocks = []
  cur_tokens = []
  prev_tok = None
  for tok in tokens:
    if _TokensCollide(prev_tok, tok):
      token_blocks.append(cur_tokens)
      cur_tokens = []
    cur_tokens.append(tok)
    if tok.type != token.COMMENT: prev_tok = tok
  token_blocks.append(cur_tokens)
  def Parse(tokens):
    untokenized = tokenize.untokenize(tokens)
    if not isinstance(untokenized, str):
      untokenized = untokenized.decode('utf-8')
    expstr = f'(\n{untokenized}\n)'
    return ast.parse(expstr, mode='eval')
  return [Parse(tokens) for tokens in token_blocks]


def _ResolveStringValue(val, ectx):
  res = ''
  j, d = 0, 0
  dclose = False
  for i, c in enumerate(val):
    if c == '{':
      if d == 0:
        res += val[j:i]
        j = i + 1
      d += 1
      if d == 2 and i == j:
        d = 0
        j = i
    elif c == '}':
      if d > 0:
        d -= 1
        if d == 0:
          exp = val[j:i]
          res += str(_GclExprEval(exp, ectx))
          j = i + 1
        dclose = False
      else:
        if dclose:
          dclose = False
          res += val[j:i]
          j = i + 1
        else:
          dclose = True

  res += val[j:]
  _DebugPrint(f'Formatted string: {res}')
  return res


def _RecursiveUpdateParents(obj, parent, opts):
  if isinstance(obj, GclDict):
    setattr(obj, '_gcl_parent_', parent)
    setattr(obj, '_gcl_opts_', opts)
    for i in obj._gcl_noresolve_values_():
      _RecursiveUpdateParents(i, obj, opts)


def _CompositeTuples(tuples, ectx):
  assert isinstance(tuples, list), (
      f'Expected list of tuples to composite; got {type(tuples)}')
  assert tuples, 'Attempting to composite empty list of tuples'
  _DebugPrint(f'Composite the following tuples: {tuples}')
  res = ectx.NewGclDict()
  for t in tuples:
    if isinstance(t, DeferredValue): res._gcl_merge_(t._gcl_resolve_(res))
    elif isinstance(t, str): res._gcl_merge_(_GclExprEval(t, ectx.AtScope(res)))
    elif isinstance(t, GclDict): res._gcl_merge_(t)
    else: raise TypeError(
        f'{yaml_point}\nUnknown composite mechanism for {type(t)}')
  return res


def _GclExprEval(expr, ectx):
  _DebugPrint(f'Evaluate: {expr}')
  chunks = _ParseIntoChunks(expr)
  vals = [_EvalGclAst(chunk, ectx) for chunk in chunks]
  if len(vals) == 1 and not isinstance(vals[0], GclDict): return vals[0]
  return _CompositeGclTuples(vals, ectx)


def _GclNameLookup(name, ectx):
  if name in ectx.scope:
    get = ectx.scope._gcl_traceable_get_(name, ectx)
    if get is None: _GclWarning(ectx.Error(f'Warning: {name} is None'))
    return get
  if ectx.scope._gcl_parent_:
    return _GclNameLookup(name, ectx.AtScope(ectx.scope._gcl_parent_))
  mnv = ectx.opts.missing_name_value
  if mnv is not YamletOptions.Error: return mnv
  ectx.Raise(NameError, f'There is no variable called `{name}` in this scope')


def _EvalGclAst(et, ectx):
  _DebugPrint(ast.dump(et))
  ev = lambda x: _EvalGclAst(x, ectx)
  match type(et):
    case ast.Expression: return ev(et.body)
    case ast.Name: return _GclNameLookup(et.id, ectx)
    case ast.Constant:
      if isinstance(et.value, str):
        return _ResolveStringValue(et.value, ectx)
      return et.value
    case ast.Attribute:
      val = ev(et.value)
      return val[et.attr]
    case ast.BinOp:
      l, r = ev(et.left), ev(et.right)
      match type(et.op):
        case ast.Add: return l + r
      raise NotImplementedError(f'Unsupported binary operation `{et.op}`')
    case ast.Call:
      fun, fun_name = None, None
      if isinstance(et.func, ast.Name):
        fun_name = et.func.id
        if fun_name in ectx.opts.functions: fun = ectx.opts.functions[fun_name]
      if not fun:
        fun = _EvalGclAst(et.func, ectx)
      if isinstance(fun, GclLambda): fun = fun.Callable(fun_name, ectx)
      if not callable(fun): ectx.Raise(
          TypeError, f'`{fun_name or ast.unparse(et.func)}` is not a function.')
      fun_args = [_EvalGclAst(arg, ectx) for arg in et.args]
      fun_kwargs = {kw.arg: _EvalContext(kw.value, ectx) for kw in et.keywords}
      return fun(*fun_args, **fun_kwargs)
  ectx.Raise(NotImplementedError,
             f'Undefined Yamlet operation `{type(et)}`')


def _CompositeGclTuples(tuples, ectx):
  res = ectx.NewGclDict()
  for t in tuples:
    if t is None: raise ValueError('Expression evaluation failed?')
    res._gcl_merge_(t)
  return res
