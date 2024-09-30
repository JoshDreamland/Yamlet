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
  def _resolvekv(self, k, v):
    if isinstance(v, DeferredValue):
      r = v._gcl_resolve_(scope=self)
      self.__setitem__(k, r)
      return r
    else:
      return v

  def __getitem__(self, key):
    return self._resolvekv(key, super().__getitem__(key))

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
        k: maybe_clone(v) for k, v in self._gcl_noresolve_items_()})

  def _gcl_has_unresolved_(self):
    for k, v in self._gcl_noresolve_items_():
      if isinstance(v, DeferredValue): return True
      if isinstance(v, GclDict) and v._gcl_has_unresolved_(): return True
    return False

  def _gcl_noresolve_values_(self): return super().values()
  def _gcl_noresolve_items_(self): return super().items()


class YamletLoader(ruamel.yaml.YAML):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    # Set custom dict type for base operations
    self.constructor.yaml_base_dict_type = GclDict
    self.representer.add_representer(GclDict, self.representer.represent_dict)

    # Override the constructor to always return our custom dict type
    self.constructor.add_constructor(
        ruamel.yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        lambda loader, node: GclDict(loader.construct_pairs(node)))


class DeferredValue:
  def __init__(self, data, yaml_point):
    self._gcl_construct_ = data
    self._gcl_cache_ = None
    self._yaml_point_ = yaml_point
  def _gcl_resolve_(self, scope):
    raise NotImplementedError('Abstract method Resolve.')


class ModuleToLoad(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, scope):
    fn = _ResolveStringValue(self._gcl_construct_, scope, self._yaml_point_)
    fn = pathlib.Path(scope._gcl_opts_.import_resolver(fn))
    _DebugPrint(f'Load the following module: {fn}')
    if not fn.exists():
      if self._gcl_construct_ == fn:
        raise FileNotFoundError(f'Could not import YamlBcl file: {self.data}')
      raise FileNotFoundError(
          f'Could not import YamlBcl file: `{fn}`\n'
          f'As evaluated from this expression: `{self.data}`')
    loaded = self._gcl_loader_(fn)
    _DebugPrint(f'Loaded:\n{loaded}')
    return loaded


class StringToSubstitute(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, scope):
    if not self._gcl_cache_: self._gcl_cache_ = _ResolveStringValue(
        self._gcl_construct_, scope, self._yaml_point_)
    return self._gcl_cache_


class TupleListToComposite(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, scope):
    if not self._gcl_cache_:
      self._gcl_cache_ = _CompositeTuples(
          self._gcl_construct_, scope, self._yaml_point_)
    return self._gcl_cache_


class ExpressionToEvaluate(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_resolve_(self, scope):
    if not self._gcl_cache_:
      self._gcl_cache_ = _GclExprEval(
          self._gcl_construct_, scope, self._yaml_point_)
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
    res = ModuleToLoad(filename, (node.start_mark, node.end_mark))
    res._gcl_loader_ = LoadCachedFile
    return res

  def GclComposite(loader, node):
    marks = (node.start_mark, node.end_mark)
    if isinstance(node, ruamel.yaml.ScalarNode):
      return TupleListToComposite(loader.construct_scalar(node).split(), marks)
    if isinstance(node, ruamel.yaml.SequenceNode):
      return TupleListToComposite(loader.construct_sequence(node), marks)
    raise ArgumentError(f'Got unexpected node type: {repr(node)}')

  def GclStrFormat(loader, node):
    return StringToSubstitute(loader.construct_scalar(node),
                              (node.start_mark, node.end_mark))

  def GclExpression(loader, node):
    return ExpressionToEvaluate(node.value, (node.start_mark, node.end_mark))

  y = YamletLoader()
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


def _ResolveStringValue(val, scope, yaml_point):
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
          res += str(_GclExprEval(exp, scope, yaml_point))
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


def _CompositeTuples(tuples, scope, yaml_point):
  assert isinstance(tuples, list), (
      f'Expected list of tuples to composite; got {type(tuples)}')
  assert tuples, 'Attempting to composite empty list of tuples'
  _DebugPrint(f'Composite the following tuples: {tuples}')
  res = GclDict()
  res._gcl_parent_ = scope
  for t in tuples:
    if isinstance(t, DeferredValue): res._gcl_merge_(t._gcl_resolve_(res))
    elif isinstance(t, str): res._gcl_merge_(_GclExprEval(t, res, yaml_point))
    elif isinstance(t, GclDict): res._gcl_merge_(t)
    else: raise TypeError(
        f'{yaml_point}\nUnknown composite mechanism for {type(t)}')
  return res


def _GclExprEval(expr, scope, yaml_point):
  _DebugPrint(f'Evaluate: {expr}')
  chunks = _ParseIntoChunks(expr)
  if len(chunks) == 1: return _EvalGclAst(chunks[0], scope, yaml_point)
  return _CompositeGclTuples([_EvalGclAst(chunk, scope, yaml_point)
                             for chunk in chunks], scope, yaml_point)


def _GclNameLookup(name, scope, yaml_point):
  if name in scope:
    if scope[name] is None: _GclWarning(f'Warning: {name} is None')
    return scope[name]
  if scope._gcl_parent_:
    return _GclNameLookup(name, scope._gcl_parent_, yaml_point)
  mnv = scope._gcl_opts_.missing_name_value
  if mnv is not YamlGclOptions.Error: return mnv
  raise NameError(f'{yaml_point[0]}\nThere is no variable called `{name}`')


def _EvalGclAst(et, scope, yaml_point):
  _DebugPrint(ast.dump(et))
  ev = lambda x: _EvalGclAst(x, scope, yaml_point)
  match type(et):
    case ast.Expression: return ev(et.body)
    case ast.Name: return _GclNameLookup(et.id, scope, yaml_point)
    case ast.Constant:
      if isinstance(et.value, str):
        return _ResolveStringValue(et.value, scope, yaml_point)
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


def _CompositeGclTuples(tuples, scope, yaml_point):
  if len(tuples) == 1: return tuples[0]
  res = GclDict()
  for t in tuples:
    if t is None: raise ValueError('Expression evaluation failed?')
    res._gcl_merge_(t)
  if not res:
    res = GclDict()
    res._gcl_parent_ = scope
  return res
