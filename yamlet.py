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
  def __init__(self, *args,
               gcl_parent, gcl_super, gcl_opts, yaml_point,
               **kwargs):
    super().__init__(*args, **kwargs)
    self._gcl_parent_ = gcl_parent
    self._gcl_super_ = gcl_super
    self._gcl_opts_ = gcl_opts
    self._yaml_point_ = yaml_point
    self._gcl_provenance_ = {}

  def _resolvekv(self, k, v, ectx=None):
    bt_msg = f'Lookup of `{k}` in this scope'
    if ectx: ectx = ectx.BranchForNameResolution(bt_msg, k, self)
    if isinstance(v, DeferredValue):
      uncaught_recursion = None
      try:
        r = v._gcl_resolve_(ectx or
            _EvalContext(self, self._gcl_opts_, self._yaml_point_, name=bt_msg))
        # XXX: This is a nice optimization but breaks accessing templates before
        # their derived types. We need to let the caching done in DeferredValue 
        # handle it for that case.
        # self.__setitem__(k, r)
        return r
      except RecursionError as r: uncaught_recursion = r
      if uncaught_recursion:
        ectx.Raise(RecursionError,
                   f'Uncaught recursion error in access.', uncaught_recursion)
      raise exception_during_access
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

  def explain_value(self, k):
    if k not in super().keys(): return f'`{k}` is not defined in this object.'
    obj = super().__getitem__(k)
    if isinstance(obj, DeferredValue):
      return obj._gcl_provenance_.ExplainUp(_prep = f'`{k}` was computed from')
    inherited = self._gcl_provenance_.get(k)
    if inherited:
      return f'`{k}` was inherited from another tuple {_TuplePointStr(inherited)}'
    return f'`{k}` was declared directly in this tuple {_TuplePointStr(self)}'

  def _gcl_merge_(self, other, ectx):
    if not isinstance(other, GclDict):
      raise TypeError('Expected GclDict to merge.')
    for k, v in other._gcl_noresolve_items_():
      if isinstance(v, GclDict):
        v1 = super().setdefault(k, v)
        if v1 is not v:
          if not isinstance(v1, GclDict):
            ectx.Raise(TypeError, f'Cannot composite `{type(v1)}` object `{k}` '
                                   'with dictionary value in extending tuple.')
          v1._gcl_merge_(v, ectx)
          v = v1
        else:
          v = v._gcl_clone_(self)
          super().__setitem__(k, v)
        assert v._gcl_parent_ is self
      elif isinstance(v, DeferredValue):
        super().__setitem__(k, v._gcl_clone_deferred_())
      else:
        self._gcl_provenance_[k] = other._gcl_provenance_.get(k, other)
        super().__setitem__(k, v)

  def _gcl_clone_(self, new_parent, new_super=None):
    '''Clones GclDicts recursively, updating parents.'''
    res = GclDict(gcl_parent=new_parent, gcl_super=new_super or self,
                  gcl_opts=self._gcl_opts_, yaml_point=self._yaml_point_)
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
  def _gcl_noresolve_get_(self, k): return super().__getitem__(k)
  def _gcl_traceable_get_(self, key, ectx):
    return self._resolvekv(key, super().__getitem__(key), ectx)


class YamletLoader(ruamel.yaml.YAML):
  def __init__(self, *args, gcl_opts, **kwargs):
    super().__init__(*args, **kwargs)
    # Set custom dict type for base operations
    self.constructor.yaml_base_dict_type = GclDict
    self.representer.add_representer(GclDict, self.representer.represent_dict)

    def ConstructGclDict(loader, node):
      return GclDict(loader.construct_pairs(node),
                     gcl_parent=None, gcl_super=None,
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


class _EvalContext:
  def __init__(self, scope, opts, yaml_point, name, parent=None, deferred=None):
    self.scope = scope
    self.opts = opts
    self._trace_point = _EvalContext._TracePoint(yaml_point, name)
    self._evaluating = id(deferred)
    self._parent = parent
    self._children = None
    self._name_deps = None

  def _PrettyError(tace_item):
    if tace_item.name: return f'{tace_item.name}\n{tace_item.start}'
    return str(tace_item.start)

  class _ScopeVisit:
    def __init__(self, ectx, scope):
      self.ectx, self.scope, self.oscope = ectx, scope, ectx.scope
    def __enter__(self): self.ectx.scope = self.scope
    def __exit__(self, exc_type, exc_val, exc_tb): self.ectx.scope = self.oscope

  class _TracePoint(YamlPoint):
    def __init__(self, yaml_point, name):
      super().__init__(yaml_point.start, yaml_point.end)
      self.name = name

  def FormatError(yaml_point, msg): return f'{yaml_point.start}\n{msg}'
  def GetPoint(self): return self._trace_point
  def Error(self, msg): return _EvalContext.FormatError(self.GetPoint(), msg)

  def NewGclDict(self, *args, gcl_parent=None, gcl_super=None, **kwargs):
    return GclDict(*args, **kwargs,
        gcl_parent=gcl_parent or self.scope,
        gcl_super=gcl_super,
        gcl_opts=self.opts,
        yaml_point=self._trace_point)

  def Branch(self, name, yaml_point, scope):
    return self._TrackChild(
        _EvalContext(scope, self.opts, yaml_point, name, parent=self))

  def BranchForNameResolution(self, lookup_description, lookup_key, scope):
    return self._TrackNameDep(lookup_key,
        _EvalContext(scope, self.opts, scope._yaml_point_, lookup_description,
                     parent=self))

  def BranchForDeferredEval(self, deferred_object, description):
    tp = _EvalContext._TracePoint(deferred_object._yaml_point_, description)
    if id(deferred_object) in self._EnumEvaluating():
      self.Raise(RecursionError, 'Dependency cycle in tuple values.')
    return self._TrackChild(
        _EvalContext(self.scope, self.opts, deferred_object._yaml_point_,
                     description, parent=self, deferred=deferred_object))

  def _TrackChild(self, child):
    if self._children: self._children.append(child)
    else: self._children = [child]
    return child

  def _TrackNameDep(self, name, child):
    if self._name_deps:
      # XXX: It would be nice to assert that `name` isn't already in the dict,
      # however, basic lambda expressions such as the test `lambda x: x + x`
      # refer to the same variable twice in one scope, and I don't think it's
      # helpful for our traceback to explain that it is adding two numbers...
      self._name_deps[name] = child
    else: self._name_deps = {name: child}
    return child

  def ExplainUp(self, indent=4, start_indent=0, _prep=None):
    ind = ' ' * start_indent
    if not _prep: _prep = 'From'
    me = self._trace_point.name
    me = me[0].lower() + me[1:]
    me = f'{_prep} {me} {str(self._trace_point.start).strip()}'
    me = ind + f'{ind}\n'.join(me.splitlines())
    ccount = ((len(self._children) if self._children else 0) + 
              (len(self._name_deps) if self._name_deps else 0))
    if ccount > 1:
      nindent = start_indent + indent
      if ccount: me += '\n'
    else: nindent = start_indent
    return me + '\n'.join(
        [f'{ind} - {child.ExplainUp(indent, nindent).lstrip()}'
         for child in (self._children or [])]) + '\n'.join(
        [f'{ind} - {child.ExplainUp(indent, nindent, _prep="With").lstrip()}'
         for child in (self._name_deps or {}).values()])

  def Scope(self, scope):
    return _EvalContext._ScopeVisit(self, scope)

  def Assert(self, expr, msg):
    if not expr: self.Raise(AssertionError, msg)
  def Raise(self, ex_class, message_sentence, e=None):
    if message_sentence == message_sentence.rstrip(): message_sentence += ' '
    raise ExceptionWithYamletTrace(ex_class,
        'An error occurred while evaluating a Yamlet expression:\n'
        + '\n'.join(_EvalContext._PrettyError(t) for t in self.FullTrace())
        + f'\n{message_sentence}See above trace for details.') from e

  def _EnumEvaluating(self):
    p = self
    while p:
      if p._evaluating: yield p._evaluating
      p = p._parent

  def FullTrace(self):
    p = self
    trace = []
    while p:
      trace.append(p._trace_point)
      p = p._parent
    return trace[::-1]


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
      self._gcl_provenance_ = ectx.BranchForDeferredEval(
          self, f'Resolving import `{self._gcl_construct_}`')
      fn = _ResolveStringValue(self._gcl_construct_, self._gcl_provenance_)
      fn = pathlib.Path(ectx.opts.import_resolver(fn))
      _DebugPrint(f'Load the following module: {fn}')
      if not fn.exists():
        if self._gcl_construct_ == fn:
          ectx.Raise(FileNotFoundError,
                     f'Could not import YamlBcl file: {self.data}')
        ectx.Raise(FileNotFoundError,
                   f'Could not import YamlBcl file: `{fn}`\n'
                   f'As evaluated from this expression: `{self.data}`.\n')
      loaded = self._gcl_loader_(fn)
      _DebugPrint(f'Loaded:\n{loaded}')
      self._gcl_cache_ = loaded
    return self._gcl_cache_


class StringToSubstitute(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      self._gcl_provenance_ = ectx.BranchForDeferredEval(
          self, f'Evaluating string `{self._gcl_construct_}`')
      self._gcl_cache_ = _ResolveStringValue(
          self._gcl_construct_, self._gcl_provenance_)
    return self._gcl_cache_


class TupleListToComposite(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      self._gcl_provenance_ = ectx.BranchForDeferredEval(
          self, f'Compositing tuple list `{self._gcl_construct_}`')
      self._gcl_cache_ = _CompositeYamlTupleList(
          self._gcl_construct_, self._gcl_provenance_)
    return self._gcl_cache_


class ExpressionToEvaluate(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      self._gcl_provenance_ = ectx.BranchForDeferredEval(
          self, f'Evaluating expression `{self._gcl_construct_.strip()}`')
      self._gcl_cache_ = _GclExprEval(
          self._gcl_construct_, self._gcl_provenance_)
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
      return _GclExprEval(self.expression, ectx.Branch(
          f'lambda `{name}`', self.yaml_point, ectx.NewGclDict(
              {params[i]: mapped_args[i] for i in range(len(params))}
          )
      ))
    return LambdaEvaluator


def _DebugPrint(msg): pass #print(msg)
def _GclWarning(msg):
  print(msg, file=sys.stderr)


def _BuiltinFuncsMapper():
  def cond(condition, if_true, if_false):
    return if_true if condition else if_false
  return {
    'cond': cond,
  }
_BUILTIN_FUNCS = _BuiltinFuncsMapper()


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
    with open(fn) as file: res = ProcessYamlGcl(file)
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


def _TuplePointStr(tup):
  return str(tup._yaml_point_.start).lstrip()


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
    try:
      return ast.parse(expstr, mode='eval')
    except Exception as e:
      raise SyntaxError(f'Failed to parse ast from `{expstr}` when processing these chunks: {token_blocks}') from e
  _DebugPrint(f'Chunked as {token_blocks}')
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


def _CompositeYamlTupleList(tuples, ectx):
  ectx.Assert(isinstance(tuples, list),
              f'Expected list of tuples to composite; got {type(tuples)}')
  ectx.Assert(tuples, 'Attempting to composite empty list of tuples')
  _DebugPrint(f'Composite the following tuples: {tuples}')
  for i, t in enumerate(tuples):
    if isinstance(t, DeferredValue): tuples[i] = t._gcl_resolve_(ectx)
    elif isinstance(t, str): tuples[i] = _GclExprEval(t, ectx)
    elif not isinstance(t, GclDict): raise TypeError(
        f'{yaml_point}\nUnknown composite mechanism for {type(t)}')
  return _CompositeGclTuples(tuples, ectx)


def _GclExprEval(expr, ectx):
  _DebugPrint(f'Evaluate: {expr}')
  chunks = _ParseIntoChunks(expr)
  vals = [_EvalGclAst(chunk, ectx) for chunk in chunks]
  if len(vals) == 1 and not isinstance(vals[0], GclDict): return vals[0]
  return _CompositeGclTuples(vals, ectx)

_BUILTIN_NAMES = {
  'up': lambda ectx: ectx.scope._gcl_parent_ or ectx.Raise(ValueError,
                     f'No enclosing tuple (value to `up`) in this context.'),
  'super': lambda ectx: ectx.scope._gcl_super_ or ectx.Raise(ValueError,
                     f'No parent tuple (value to `super`) in this context.'),
}
def _GclNameLookup(name, ectx):
  if name in _BUILTIN_NAMES:
    return _BUILTIN_NAMES[name](ectx)
  if name in ectx.scope:
    get = ectx.scope._gcl_traceable_get_(name, ectx)
    if get is None: _GclWarning(ectx.Error(f'Warning: {name} is None'))
    return get
  if ectx.scope._gcl_parent_:
    with ectx.Scope(ectx.scope._gcl_parent_):
      return _GclNameLookup(name, ectx)
  mnv = ectx.opts.missing_name_value
  if mnv is not YamletOptions.Error: return mnv
  ectx.Raise(NameError, f'There is no variable called `{name}` in this scope.')


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
      if et.attr in _BUILTIN_NAMES:
        with ectx.Scope(val): return _BUILTIN_NAMES[et.attr](ectx)
      if isinstance(val, GclDict): return val._gcl_traceable_get_(et.attr, ectx)
      return val[et.attr]
    case ast.BinOp:
      l, r = ev(et.left), ev(et.right)
      match type(et.op):
        case ast.Add: return l + r
      ectx.Raise(NotImplementedError, f'Unsupported binary operator `{et.op}`.')
    case ast.Call:
      fun, fun_name = None, None
      if isinstance(et.func, ast.Name):
        fun_name = et.func.id
        if fun_name in ectx.opts.functions: fun = ectx.opts.functions[fun_name]
        elif fun_name in _BUILTIN_FUNCS: fun = _BUILTIN_FUNCS[fun_name]
      if not fun:
        fun = _EvalGclAst(et.func, ectx)
      if isinstance(fun, GclLambda): fun = fun.Callable(fun_name, ectx)
      if not callable(fun): ectx.Raise(
          TypeError, f'`{fun_name or ast.unparse(et.func)}` is not a function.')
      fun_args = [_EvalGclAst(arg, ectx) for arg in et.args]
      fun_kwargs = {kw.arg: _EvalGclAst(kw.value, ectx) for kw in et.keywords}
      return fun(*fun_args, **fun_kwargs)
    case ast.Dict:
      def EvalKey(k):
        if isinstance(k, ast.Name): return k.id
        if isinstance(k, ast.Constant):
          if isinstance(et.value, str):
            return _ResolveStringValue(et.value, ectx)
        ectx.Raise(
            KeyError,
            'Yamlet keys should be names or strings. Got:\n{ast.dump(et)}')
      def DeferAst(v):
        return ExpressionToEvaluate(ast.unparse(v), ectx.GetPoint())
      return ectx.NewGclDict({EvalKey(k): DeferAst(v)
                              for k,v in zip(et.keys, et.values)})
  ectx.Raise(NotImplementedError,
             f'Undefined Yamlet operation `{type(et)}`:\n{ast.dump(et)}')


def _CompositeGclTuples(tuples, ectx):
  res = None
  for t in tuples:
    if t is None: ectx.Raise(ValueError, 'Expression evaluation failed?')
    if res: res = res._gcl_clone_(ectx.scope)
    else: res = ectx.NewGclDict()
    res._gcl_merge_(t, ectx)
  return res
