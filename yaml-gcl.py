import io
import pathlib
import token
import tokenize
import yaml

from collections import deque

class YamlGclOptions:
  def __init__(self, import_resolver=None):
    self.import_resolver = import_resolver or str

class DeferredValue:
  def __init__(self, data):
    self._gcl_data_ = data
    self._gcl_cache_ = None
  def _gcl_resolve_():
    raise NotImplementedError('Abstract method Resolve.')

def _RecursiveUpdateParents(obj):
  if type(obj) is dict:
    for i in obj.values():
      i._gcl_parent_ = obj
      _RecursiveUpdateParents(i)

def DynamicScopeLoader(opts=YamlGclOptions()):
  loaded_modules = {}
  modules_to_load = deque()

  class ModuleToLoad(DeferredValue):
    def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
    def _gcl_resolve_(self):
      fn = ResolveStringValue(self._gcl_construct_)
      fn = pathlib.Path(opts.import_resolver(fn))
      if not fn.exists():
        if self._gcl_construct_ == fn:
          raise FileNotFoundError(f'Could not import YamlBcl file: {self.data}')
        raise FileNotFoundError(
            f'Could not import YamlBcl file: `{fn}`\n'
            f'As evaluated from this expression: `{self.data}`')
      return LoadCachedFile(fn)

  class StringToSubstitute(DeferredValue):
    def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
    def _gcl_resolve_(self):
      fn = ResolveStringValue(self._gcl_construct_)

  class TupleListToComposite(DeferredValue):
    def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
    def _gcl_resolve_(self):
      if not self._gcl_cache_:
        self._gcl_cache_ = CompositeTuples(self._gcl_construct_)
      return self._gcl_cache_

  def LoadCachedFile(fn):
    fn = fn.resolve()
    if fn in loaded_modules:
      res = loaded_modules[fn]
      if res is None:
        raise RecursionError(f'Processing config `{fn}` results in recursion. '
                             'This isn\'t supposed to happen, as import loads '
                             'are deferred until name lookup.')
    loaded_modules[fn] = None
    with open(fn) as file: loaded_modules[fn] = ProcessYamlGcl(file.read())

  def GclImport(loader, node):
    filename = loader.construct_scalar(node)
    return ModuleToLoad(filename)

  def GclComposite(loader, node):
    if type(node) is yaml.ScalarNode:
      return TupleListToComposite(loader.construct_scalar(node).split())
    if type(node) is yaml.SequenceNode:
      return TupleListToComposite(loader.construct_sequence())
    
    print('Invoked GclComposite')
    print(repr(node))

  def GclStrFormat(loader, node):
    print('Invoked GclStrFormat')
    print(repr(node))
  
  def ProcessYamlGcl(ygcl):
    loader = yaml.SafeLoader
    loader.add_constructor("!import", GclImport)
    loader.add_constructor("!composite", GclComposite)
    loader.add_constructor("!fmt", GclStrFormat)
    # loader.add_constructor("!expr", GclExpression)
    tup = yaml.load(ygcl, loader)
    _RecursiveUpdateParents(tup)
    return tup

  class Result():
    def load(self, filename):
      with open(filename) as fn: return self.loads(fn.read())
    def loads(self, yaml_gcl): return ProcessYamlGcl(yaml_gcl)
  return Result()


def TokensCollide(t1, t2):
  if not t1: return False
  colliding_tokens = {token.NAME, token.NUMBER, token.STRING, token.OP}
  if t1.type not in colliding_tokens or t2.type not in colliding_tokens:
    return False
  if t1.type == token.STRING and t2.type == token.STRING: return False
  if t1.type == token.NAME and t2.type == token.OP:  return t2.string == '{'
  if t2.type == token.OP and t2.string not in '([{': return False
  if t1.type == token.OP and t1.string not in ')]}': return False
  return True

def insert_implicit_multiplication(expr):
  tokens = tokenize.tokenize(io.BytesIO(expr.encode('utf-8')).readline)
  new_tokens = []
  prev_tok = None
  for tok in tokens:
    if TokensCollide(prev_tok, tok):
      new_tokens.append(tokenize.TokenInfo(tokenize.OP, '*', prev_tok.end, tok.start, expr))
    new_tokens.append(tok)
    if tok.type != token.COMMENT: prev_tok = tok
  # Reconstruct the expression
  new_expr = tokenize.untokenize(new_tokens)
  return new_expr.decode('utf-8')

expr = "a.b.c d.e.f (a + b)(c + d) {}"
new_expr = insert_implicit_multiplication(expr)
print(new_expr)

loader = DynamicScopeLoader()
loader.load('yaml-gcl.yaml')
