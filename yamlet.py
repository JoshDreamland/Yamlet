import ast
import copy
import io
import pathlib
import ruamel.yaml
import sys
import token
import tokenize

from collections import deque

class YamlGclOptions:
  Error = ['error']
  def __init__(self, import_resolver=None, missing_name_value=Error):
    self.import_resolver = import_resolver or str
    self.missing_name_value = missing_name_value


class GclDict(dict):
  def __init__(self, *args, gcl_parent, gcl_opts, yaml_point, **kwargs):
    super().__init__(*args, **kwargs)
    self._gcl_parent_ = gcl_parent
    self._gcl_opts_ = gcl_opts
    self._yaml_point_ = yaml_point

  def _resolvekv(self, k, v, ectx=None):
    if isinstance(v, DeferredValue):
      r = v._gcl_resolve_(ectx or
          _EvalContext(self, self._gcl_opts_, self._yaml_point_))
      self.__setitem__(k, r)
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
    other = other._gcl_clone_unresolved_()
    for k, v in other._gcl_noresolve_items_():
      super().__setitem__(k, v)

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


def _PrettyError(mark):
  return str(mark)
  with open(filepath, 'r') as f: lines = f.readlines()
  line_content = lines[mark.line]
  caret_line = ' ' * mark.column + '^'
  return f'{line_content}\n{caret_line}'

class _EvalContext:
  def __init__(self, scope, opts, yaml_point):
    self.scope = scope
    self.opts = opts
    self.trace = [yaml_point]
    self.evaluating = set()

  def AddTrace(self, deferred_object):
    self.trace.append(deferred_object._yaml_point_)
    if deferred_object in self.evaluating:
      self.Raise(RecursionError, 'Dependency cycle in tuple values.')
    self.evaluating.add(deferred_object)

  def Error(self, msg):
    return f'{self.trace[-1].start}\n{msg}'

  def NewGclDict(self):
    return GclDict(
        gcl_parent=self.scope, gcl_opts=self.opts, yaml_point=self.trace[-1])

  def AtScope(self, scope):
    res = _EvalContext(scope, self.opts, list(self.trace))
    return res

  def Raise(self, ex_class, message_sentence):
    raise ExceptionWithYamletTrace(ex_class,
        'An error occurred while evaluating a Yamlet expression: '
        + '\n\n'.join(_PrettyError(t.start) for t in self.trace)
        + f'\n\n{message_sentence} See above trace for details.')


class DeferredValue:
  def __init__(self, data, yaml_point):
    self._gcl_construct_ = data
    self._gcl_cache_ = None
    self._yaml_point_ = yaml_point
  def _gcl_resolve_(self, ectx):
    raise NotImplementedError('Abstract method Resolve.')


class ModuleToLoad(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      ectx.AddTrace(self)
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
      ectx.AddTrace(self)
      self._gcl_cache_ = _ResolveStringValue(self._gcl_construct_, ectx)
    return self._gcl_cache_


class TupleListToComposite(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      ectx.AddTrace(self)
      self._gcl_cache_ = _CompositeTuples(self._gcl_construct_, ectx)
    return self._gcl_cache_


class ExpressionToEvaluate(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, ectx):
    if not self._gcl_cache_:
      ectx.AddTrace(self)
      self._gcl_cache_ = _GclExprEval(self._gcl_construct_, ectx)
    return self._gcl_cache_


def _DebugPrint(msg): pass #print(msg)
def _GclWarning(msg):
  print(msg, file=sys.stderr)


def DynamicScopeLoader(opts=YamlGclOptions()):
  loaded_modules = {}
  modules_to_load = deque()

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

  y = YamletLoader(gcl_opts=opts)
  y.constructor.add_constructor("!import", GclImport)
  y.constructor.add_constructor("!composite", GclComposite)
  y.constructor.add_constructor("!fmt", GclStrFormat)
  y.constructor.add_constructor("!expr", GclExpression)

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
  for i, c in enumerate(val):
    if c == '{':
      if d == 0:
        res += val[j:i]
        j = i + 1
      d += 1
    elif c == '}':
      if d > 0:
        d -= 1
        if d == 0:
          exp = val[j:i]
          res += str(_GclExprEval(exp, ectx))
          j = i + 1
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
  if len(chunks) == 1: return _EvalGclAst(chunks[0], ectx)
  return _CompositeGclTuples([_EvalGclAst(chunk, ectx) for chunk in chunks], ectx)


def _GclNameLookup(name, ectx):
  if name in ectx.scope:
    get = ectx.scope._gcl_traceable_get_(name, ectx)
    if get is None: _GclWarning(ectx.Error(f'Warning: {name} is None'))
    return get
  if ectx.scope._gcl_parent_:
    return _GclNameLookup(name, ectx.AtScope(ectx.scope._gcl_parent_))
  mnv = ectx.opts.missing_name_value
  if mnv is not YamlGclOptions.Error: return mnv
  raise NameError(ectx.Error(f'There is no variable called `{name}`'))


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
  raise NotImplementedError(f'Couldn\'t understand {type(et)} AST node')


def _CompositeGclTuples(tuples, ectx):
  res = ectx.NewGclDict()
  for t in tuples:
    if t is None: raise ValueError('Expression evaluation failed?')
    res._gcl_merge_(t)
  return res
