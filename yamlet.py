import ast
import copy
import io
import keyword
import pathlib
import ruamel.yaml
import sys
import token
import tokenize

ConstructorError = ruamel.yaml.constructor.ConstructorError
class YamletBaseException(Exception): pass


class YamletOptions:
  Error = ['error']

  CACHE_VALUES = 1
  CACHE_NOTHING = 2
  CACHE_DEBUG = 3

  def __init__(self, import_resolver=None, missing_name_value=Error,
               functions={}, globals={}, caching=CACHE_VALUES):
    self.import_resolver = import_resolver or str
    self.missing_name_value = missing_name_value
    self.functions = functions
    self.globals = globals
    self.caching = caching


class Cloneable:
  '''Clonable objects can be duplicated (via deep-copy) at any time.

  Any cloned object can be mutated freely without contaminating the parent.
  This is critical for proper templating implementation.
  All object references within a clone (such as parent pointers) should also be
  updated to point within the new cloned ecosystem.
  '''
  def yamlet_clone(self, new_scope):
    ectx.Raise(NotImplementedError, 'A class which implements '
               '`yamlet.Cloneable` should implement yamlet_clone(); '
               f'`{type(self).__name__}` does not.')


class Compositable(Cloneable):
  '''Compositable objects are objects which can be merged together (composited).

  They must also be cloneable, so that merging them does not destroy the
  original template.
  '''
  def yamlet_merge(self, other, ectx):
    ectx.Raise(NotImplementedError, 'A class which implements '
               '`yamlet.Compositable` should implement `yamlet_merge()`; '
               f'`{type(self).__name__}` does not.')


class GclDict(dict, Compositable):
  def __init__(self, *args,
               gcl_parent, gcl_super, gcl_opts, yaml_point, preprocessors,
               **kwargs):
    super().__init__(*args, **kwargs)
    self._gcl_parent_ = gcl_parent
    self._gcl_super_ = gcl_super
    self._gcl_opts_ = gcl_opts
    self._gcl_preprocessors_ = preprocessors or {}
    self._gcl_provenance_ = {}
    self._yaml_point_ = yaml_point

  def _resolvekv(self, k, v, ectx=None):
    bt_msg = f'Lookup of `{k}` in this scope'
    if ectx: ectx = ectx.BranchForNameResolution(bt_msg, k, self)
    if isinstance(v, DeferredValue):
      uncaught_recursion = None
      ectx = ectx or (
          _EvalContext(self, self._gcl_opts_, self._yaml_point_, name=bt_msg))
      try:
        r = v._gcl_resolve_(ectx)
        # XXX: This is a nice optimization but breaks accessing templates before
        # their derived types. We need to let the caching done in DeferredValue
        # handle it for that case.
        # self.__setitem__(k, r)
        return r
      except RecursionError as r:
        raise
        uncaught_recursion = r
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

  def __contains__(self, key):
    return super().get(key, null) is not null

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

  def yamlet_merge(self, other, ectx):
    ectx.Assert(isinstance(other, Compositable),
                'Expected Compositable to merge.', ex_class=TypeError)
    for k, v in other._gcl_noresolve_items_():
      if isinstance(v, Compositable):
        v1 = super().setdefault(k, v)
        if v1 is not v:
          if not isinstance(v1, Compositable):
            ectx.Raise(TypeError, f'Cannot composite `{type(v1)}` object `{k}` '
                                   'with dictionary value in extending tuple.')
          v1.yamlet_merge(v, ectx)
          v = v1
        else:
          v = v.yamlet_clone(self)
          super().__setitem__(k, v)
        assert v._gcl_parent_ is self
      elif isinstance(v, Cloneable):
        super().__setitem__(k, v.yamlet_clone(self))
      elif v or (v not in (null, external, _undefined)):
        self._gcl_provenance_[k] = other._gcl_provenance_.get(k, other)
        super().__setitem__(k, v)
      elif v is null:
        self._gcl_provenance_[k] = other._gcl_provenance_.get(k, other)
        super().pop(k, None)
      elif v is _undefined:
        ectx.Raise(AssertionError,
                   'An undefined value was propagated into a Yamlet tuple.')

    for k, v in other._gcl_preprocessors_.items():
      if k not in self._gcl_preprocessors_:
        self._gcl_preprocessors_[k] = v.yamlet_clone(self)
    self._gcl_preprocess_(ectx)

  def _gcl_preprocess_(self, ectx):
    if not self._gcl_parent_:
      self._gcl_parent_ = ectx.scope
      assert self._gcl_parent_ is not self
    ectx = ectx.Branch('Yamlet Preprocessing', ectx._trace_point, self)
    for _, v in self._gcl_preprocessors_.items():
      v._gcl_preprocess_(ectx)
    erased = set()
    for k, v in self._gcl_noresolve_items_():
      if isinstance(v, DeferredValue) and v._gcl_is_undefined_(ectx):
        erased.add(k)
    for k in erased: super().pop(k)

  def yamlet_clone(self, new_scope):
    cloned_preprocessors = {k: v.yamlet_clone(new_scope)
                            for k, v in self._gcl_preprocessors_.items()}
    res = GclDict(gcl_parent=new_scope, gcl_super=self,
                  gcl_opts=self._gcl_opts_, preprocessors=cloned_preprocessors,
                  yaml_point=self._yaml_point_)
    for k, v in self._gcl_noresolve_items_():
      if isinstance(v, Cloneable): v = v.yamlet_clone(res)
      res.__setitem__(k, v)
    return res

  def evaluate_fully(self, ectx=None):
    ectx = (
        ectx.Branch('Fully evaluating nested tuple', self._yaml_point_, self)
        if ectx else _EvalContext(self, self._gcl_opts_, self._yaml_point_,
                                  name='Fully evaluating Yamlet tuple'))
    def ev(v):
      while isinstance(v, DeferredValue): v = v._gcl_resolve_(ectx)
      if isinstance(v, GclDict): v = v.evaluate_fully(ectx)
      return v
    return {k: ev(v) for k, v in self._gcl_noresolve_items_()}

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

    def UndefinedConstructor(self, node):
      raise ConstructorError(
          None, None,  f'No constructor bound for tag `{node.tag}`',
          node.start_mark)

    # Raise on undefined tags
    self.constructor.add_constructor(None, UndefinedConstructor)


def _NoneType(name):
  class Nothing:
    def __bool__(self): return False
    def __nonzero__(self): return False
    def __str__(self): return name
    def __repr__(self): return name
  return Nothing


def _BuiltinNones():
  class external(_NoneType('external')): pass
  class null(_NoneType('null')): pass
  class undefined(_NoneType('undefined')): pass
  class empty(_NoneType('empty')): pass
  return external(), null(), undefined(), empty()
external, null, _undefined, _empty = _BuiltinNones()


'''▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
░▒▓██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀██▓▒░
░▒▓██  Context tracking:  Information about (and used during) evaluation.  ██▓▒░
░▒▓██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄██▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
  ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒'''


def exceptions(bc):
  '''Looks like a namespace in stack traces but is really a function.'''
  class YamletException(bc, YamletBaseException):
    def __init__(self, message, details):
      super().__init__(message)
      self.details = details
      self.traced_message = message
    def __str__(self): return self.traced_message
  return YamletException


class ExceptionWithYamletTrace(Exception):
  def __init__(self, ex_class, message):
    super().__init__(message)
    self.ex_class = ex_class
    self.traced_message = message
  def rewind(self):
    return exceptions(self.ex_class)(self.traced_message, self)


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
        preprocessors=None,
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

  def Assert(self, expr, msg, ex_class=AssertionError):
    if not expr: self.Raise(ex_class, msg)

  def Raise(self, ex_class, message_sentence, e=None):
    if message_sentence == message_sentence.rstrip(): message_sentence += ' '
    raise ExceptionWithYamletTrace(ex_class,
        f'{ex_class.__name__} occurred while evaluating a Yamlet expression:\n'
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


'''▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
░▒▓██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀██▓▒░
░▒▓██  Deferred Value:  Unit for template value application.               ██▓▒░
░▒▓██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄██▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
  ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒'''

class DeferredValue(Cloneable):
  def __init__(self, data, yaml_point):
    self._gcl_construct_ = data
    self._gcl_cache_ = _empty
    self._yaml_point_ = yaml_point

  def __eq__(self, other):
    return (isinstance(other, DeferredValue) and
            other._gcl_construct_ == self._gcl_construct_)

  def _gcl_resolve_(self, ectx):
    if self._gcl_cache_ is _empty:
      self._gcl_provenance_ = ectx.BranchForDeferredEval(
          self, self._gcl_explanation_())
      res = self._gcl_evaluate_(self._gcl_construct_, self._gcl_provenance_)
      if ectx.opts.caching == YamletOptions.CACHE_NOTHING: return res
      if ectx.opts.caching == YamletOptions.CACHE_DEBUG:
        if getattr(self, '_gcl_cache_debug_', _empty) is not _empty:
          assert res == self._gcl_cache_debug_, ('Internal error: Cache bug! '
              f'Cached value `{self._gcl_cache_debug_}` is not `{res}`!')
        self._gcl_cache_debug_ = res
        return res
      self._gcl_cache_ = res
    return self._gcl_cache_

  def yamlet_clone(self, new_scope):
    return type(self)(self._gcl_construct_, self._yaml_point_)

  def _gcl_is_undefined_(self, ectx): return False

  def __str__(self):
    return (f'<Unevaluated: {self._gcl_construct_}>' if not self._gcl_cache_
            else str(self._gcl_cache_))
  def __repr__(self):
    return f'<Unevaluated: {self._gcl_construct_}>'


class ModuleToLoad(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)

  def _gcl_explanation_(self):
    return f'Resolving import `{self._gcl_construct_}`'

  def _gcl_evaluate_(self, value, ectx):
    fn = _ResolveStringValue(value, ectx)
    fn = pathlib.Path(ectx.opts.import_resolver(fn))
    _DebugPrint(f'Load the following module: {fn}')
    if not fn.exists():
      if value == fn:
        ectx.Raise(FileNotFoundError,
                   f'Could not import YamlBcl file: {value}')
      ectx.Raise(FileNotFoundError,
                 f'Could not import YamlBcl file: `{fn}`\n'
                 f'As evaluated from this expression: `{value}`.\n')
    loaded = self._gcl_loader_(fn)
    _DebugPrint('Loaded:\n', loaded)
    return loaded


class StringToSubstitute(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_explanation_(self):
    return f'Evaluating string `{self._gcl_construct_}`'
  def _gcl_evaluate_(self, value, ectx):
    return _ResolveStringValue(value, ectx)


class TupleListToComposite(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_explanation_(self):
    return f'Compositing tuple list `{self._gcl_construct_}`'
  def _gcl_evaluate_(self, value, ectx):
      return _CompositeYamlTupleList(value, ectx)


class ExpressionToEvaluate(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_explanation_(self):
    return f'Evaluating expression `{self._gcl_construct_.strip()}`'
  def _gcl_evaluate_(self, value, ectx):
    return _GclExprEval(value, ectx)


class IfLadderTableIndex(DeferredValue):
  def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs)
  def _gcl_explanation_(self):
    return f'Pre-evaluating if-else ladder'
  def _gcl_evaluate_(self, value, ectx):
    for i, cond in enumerate(value.cond_dvals):
      if cond._gcl_resolve_(ectx):
        return i
    return -1


class IfLadderItem(DeferredValue):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  def _gcl_explanation_(self):
    return f'Evaluating item in if-else ladder'

  def _gcl_evaluate_(self, value, ectx):
    ladder, table = value
    ladder = ectx.scope._gcl_preprocessors_.get(id(ladder))
    ectx.Assert(ladder,
                'Internal error: The preprocessor `!if` directive from which '
                'this value was assigned was not inherited...')
    index = ladder.index._gcl_resolve_(ectx)
    result = table[index]
    while isinstance(result, DeferredValue): result = result._gcl_resolve_(ectx)
    return result

  def yamlet_clone(self, new_scope):
    return IfLadderItem((self._gcl_construct_[0], [
        e.yamlet_clone(new_scope) if isinstance(e, Cloneable) else e
        for i, e in enumerate(self._gcl_construct_[1])]), self._yaml_point_)
    return res

  def _gcl_is_undefined_(self, ectx):
    try: result = self._gcl_resolve_(ectx)
    except Exception as e: return False  # Keep and let user discover the error.
    if isinstance(result, DeferredValue): return result._gcl_is_undefined_(ectx)
    return result is _undefined


class FlatCompositor(DeferredValue):
  def __init__(self, *args, varname, **kwargs):
    super().__init__(*args, **kwargs)
    self._gcl_varname_ = varname
  def _gcl_explanation_(self):
    return f'Compositing values given for `{self._gcl_varname_}`'

  def _gcl_evaluate_(self, value, ectx):
    active_composite = []
    for term in value:
      while isinstance(term, DeferredValue): term = term._gcl_resolve_(ectx)
      if term: active_composite.append(term)
      else:
        if term is _undefined: continue
        if term is external: ectx.Raise(ValueError,
            f'External value found while evaluating `{self._gcl_varname_}`.')
        active_composite.append(term)
    if len(active_composite) == 1: return active_composite[0]
    if any(not isinstance(term, Compositable) for term in active_composite):
      ectx.Raise(ValueError, f'Multiple non-compisitable values given for '
                             f'`{self._gcl_varname_}`.')
    return _CompositeGclTuples(active_composite, ectx)

  def _gcl_is_undefined_(self, ectx):
    for term in self._gcl_construct_:
      if not isinstance(term, DeferredValue): return False
      if not term._gcl_is_undefined_(ectx): return False
    return True

  def yamlet_clone(new_scope):
    return FlatCompositor(
        [v.yamlet_clone(new_scope) if isinstance(v, Cloneable) else v
            for v in self._gcl_construct_], self._yaml_point_)


class GclLambda:
  '''GclLambda isn't actually a DeferredValue, but they appear similar in YAML.

  The glass actually provides an interface to make itself callable, and the
  `_EvalGclAst` checks for its type directly before raising that an object
  is not callable.
  '''
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


class PreprocessingTuple(DeferredValue, Compositable):
  def __init__(self, tup, yaml_point=None):
    super().__init__(tup, yaml_point or tup._yaml_point_)
  def _gcl_explanation_(self):
    return f'Preprocessing Yamlet tuple literal'
  def _gcl_evaluate_(self, value, ectx):
    value._gcl_preprocess_(ectx)
    return value
  def keys(self): return self._gcl_construct_.keys()
  def _gcl_noresolve_items_(self):
    return self._gcl_construct_._gcl_noresolve_items_()
  def __getattr__(self, attr):
    if attr == '_gcl_parent_': return self._gcl_construct_._gcl_parent_
    if attr == '_gcl_provenance_': return self._gcl_construct_._gcl_provenance_
    if attr == '_gcl_preprocessors_':
      return self._gcl_construct_._gcl_preprocessors_
    raise AttributeError(f'PreprocessingTuple has no attribute `{attr}`')
  def yamlet_clone(self, new_scope):
    return PreprocessingTuple(self._gcl_construct_.yamlet_clone(new_scope))
  def yamlet_merge(self, other, ectx):
    self._gcl_construct_.yamlet_merge(other, ectx)


'''▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
░▒▓█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█▓▒░
░▒▓█ Preprocessing Directives:  Execution of Yamlet-specific preprocessors. █▓▒░
░▒▓█▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
  ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒'''


class PreprocessingDirective():
  def __init__(self, data, yaml_point):
    self._gcl_construct_ = data
    self._yaml_point_ = yaml_point
  def yamlet_clone(self, new_scope):
    raise NotImplementedError(
        f'Internal error: clone() not implemented in {type(self).__name__}')
  def _gcl_preprocess_(self, ectx):
    raise NotImplementedError(
        f'Internal error: preprocess() not implemented in {type(self).__name__}'
    )


class YamletIfStatement(PreprocessingDirective): pass
class YamletElifStatement(PreprocessingDirective): pass
class YamletElseStatement(PreprocessingDirective): pass
class YamletIfElseLadder(PreprocessingDirective):
  def __init__(self, k, v):
    self.if_statement = (k, v)
    self.else_statement = None
    self.elif_statements = []
    self.all_vars = set(v.keys())

  def PutElif(self, k, v):
    self.elif_statements.append((k, v))
    self.all_vars |= v.keys()

  def PutElse(self, k, v):
    self.else_statement = (k, v)
    self.all_vars |= v.keys()

  def Finalize(self, filtered_pairs, cErr):
    size = 2 + len(self.elif_statements)
    arrays = {k: [_undefined] * size for k in self.all_vars}
    ladder_point = self.if_statement[0]._yaml_point_
    for k, v in self.if_statement[1]._gcl_noresolve_items_():
      arrays[k][0] = v
    for i, elif_statement in enumerate(self.elif_statements):
      for k, v in elif_statement[1]._gcl_noresolve_items_():
        arrays[k][i + 1] = v
    if self.else_statement:
      for k, v in self.else_statement[1]._gcl_noresolve_items_():
        arrays[k][-1] = v
    for k, v in arrays.items():
      v0 = IfLadderItem((self, v), ladder_point)
      v1 = filtered_pairs.setdefault(k, v0)
      if v0 is not v1:
        filtered_pairs[k] = FlatCompositor([v1, v0], ladder_point, varname=k)
    expr_points = [self.if_statement[0]] + [e[0] for e in self.elif_statements]
    self.cond_dvals = [ExpressionToEvaluate(ep._gcl_construct_, ep._yaml_point_)
                       for ep in expr_points]
    self.index = IfLadderTableIndex(self, ladder_point)

  def AddPreprocessors(self, preprocessors):
    preprocessors[id(self)] = self
    preprocessors |= self.if_statement[1]._gcl_preprocessors_
    for elif_statement in self.elif_statements:
      preprocessors |= elif_statement[1]._gcl_preprocessors_
    if self.else_statement:
      preprocessors |= self.else_statement[1]._gcl_preprocessors_

  def _gcl_preprocess_(self, ectx): pass

  def yamlet_clone(self, new_scope):
    other = copy.copy(self)
    other.cond_dvals = [dv.yamlet_clone(new_scope) for dv in self.cond_dvals]
    other.index = self.index.yamlet_clone(new_scope)
    other.index._gcl_construct_ = self
    return other


def _DebugPrint(*args, **kwargs): pass #print(*args, **kwargs)
def _GclWarning(*args, **kwargs): print(*args, file=sys.stderr, **kwargs)


def ProcessYamlPairs(mapping_pairs, gcl_opts, yaml_point):
  filtered_pairs = {}
  preprocessors = {}
  if_directive = None
  cErr = lambda msg, v: ConstructorError(None, None, msg, v._yaml_point_.start)
  notDict = lambda v: (
      not isinstance(v, GclDict) and not isinstance(v, PreprocessingTuple))
  notDictErr = lambda k, v: cErr(
      'Yamlet preprocessor conditionals should be mappings. '
      f'For individual values, use `!expr cond(cond, t, f)`.\nGot: {v}', k)
  def terminateIfDirective():
    nonlocal if_directive, preprocessors
    if if_directive:
      if_directive.Finalize(filtered_pairs, cErr)
      if_directive.AddPreprocessors(preprocessors)
      if_directive = None
  for k, v in mapping_pairs:
    if isinstance(k, PreprocessingDirective):
      if isinstance(k, YamletIfStatement):
        if notDict(v): raise notDictErr(k, v)
        terminateIfDirective()
        if_directive = YamletIfElseLadder(k, v)
      elif isinstance(k, YamletElifStatement):
        if notDict(v): raise notDictErr(k, v)
        if not if_directive:
          raise cErr('`!elif` directive is not paired to an `!if` directive', k)
        if_directive.PutElif(k, v)
      elif isinstance(k, YamletElseStatement):
        if notDict(v): raise notDictErr(k, v)
        if not if_directive:
          raise cErr('`!else` directive is not paired to an `!if` directive', k)
        if_directive.PutElse(k, v)
        terminateIfDirective()
    elif isinstance(k, DeferredValue):
      terminateIfDirective()
      # XXX: Fringe use-case would be to allow a kind of "!const" tag to
      # appear here so that local evaluations can be used as keys.
      raise cErr('Yamlet keys from YAML mappings must be constant', k)
    else:
      terminateIfDirective()
      if k in filtered_pairs:
        raise cErr(f'Duplicate tuple key `{k}`: '
                   'this is defined to be an error in Yamlet 0.0')
      filtered_pairs[k] = v
  terminateIfDirective()
  res = GclDict(filtered_pairs,
                gcl_parent=None, gcl_super=None, gcl_opts=gcl_opts,
                preprocessors=preprocessors, yaml_point=yaml_point)
  if preprocessors: return PreprocessingTuple(res)
  return res


'''▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
░▒▓██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀██▓▒░
░▒▓██  DynamicScopeLoader:  The user interface to Yamlet.                  ██▓▒░
░▒▓██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄██▓▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
  ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒'''

# TODO: Scrub this section; reconcile with the loader class above.
# We really don't need closure-style member protection, here; if a user wants
# to fuck up our internals, that's on them.

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

  def ConstructGclDict(loader, node):
    return ProcessYamlPairs(
        loader.construct_pairs(node), gcl_opts=opts,
        yaml_point=YamlPoint(start=node.start_mark, end=node.end_mark))

  def GclComposite(loader, node):
    marks = YamlPoint(node.start_mark, node.end_mark)
    if isinstance(node, ruamel.yaml.ScalarNode):
      return TupleListToComposite(loader.construct_scalar(node).split(), marks)
    if isinstance(node, ruamel.yaml.SequenceNode):
      return TupleListToComposite(loader.construct_sequence(node), marks)
    raise ConstructorError(None, None,
        f'Yamlet `!composite` got unexpected node type: {repr(node)}',
        node.start_mark)

  def ScalarNode(tp):
    def Constructor(loader, node):
      return tp(loader.construct_scalar(node),
                YamlPoint(node.start_mark, node.end_mark))
    return Constructor

  def ConstructConstant(tag, val):
    def Constructor(loader, node):
      n = loader.construct_scalar(node)
      if n != '': raise ConstructorError(None, None,
          f'Yamlet `!{tag}` got unexpected node type: {repr(node)}',
          node.start_mark)
      return val
    return Constructor

  def ConstructElse(loader, node):
    marks = YamlPoint(node.start_mark, node.end_mark)
    if isinstance(node, ruamel.yaml.ScalarNode):
      s = loader.construct_scalar(node)
      if s: raise ruamel.yaml.constructor.ConstructorError(
          None, None,
          f'A Yamlet `!else` should not have a value attached, '
          f'but contained {s}', node.start_mark)
      return YamletElseStatement('', marks)
    raise ruamel.yaml.constructor.ConstructorError(
        f'Yamlet `!else` got unexpected node type: {repr(node)}')

  y = YamletLoader(gcl_opts=opts)
  yc = y.constructor
  yc.add_constructor(
      ruamel.yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, ConstructGclDict)
  yc.add_constructor("!import",    GclImport)
  yc.add_constructor("!composite", GclComposite)
  yc.add_constructor("!fmt",       ScalarNode(StringToSubstitute))
  yc.add_constructor("!expr",      ScalarNode(ExpressionToEvaluate))
  yc.add_constructor("!lambda",    ScalarNode(GclLambda))
  yc.add_constructor("!if",        ScalarNode(YamletIfStatement))
  yc.add_constructor("!elif",      ScalarNode(YamletElifStatement))
  yc.add_constructor("!else",      ConstructElse)
  yc.add_constructor("!else:",     ConstructElse)
  yc.add_constructor("!null",      ConstructConstant('null',     null))
  yc.add_constructor("!external",  ConstructConstant('external', external))

  def ProcessYamlGcl(ygcl):
    tup = y.load(ygcl)
    ectx = _EvalContext(None, opts, tup._yaml_point_,
                        'Evaluating preprocessors in Yamlet document.')
    while isinstance(tup, DeferredValue): tup = tup._gcl_resolve_(ectx)
    _RecursiveUpdateParents(tup, None, opts)
    return tup

  class Result():
    def load(self, filename):
      with open(filename) as fn: return self.loads(fn)
    def loads(self, yaml_gcl): return ProcessYamlGcl(yaml_gcl)
  return Result()


'''▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
░▒▓██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀██▓▒░
░▒▓██  Expression Parsing:  Hammering GCL constructs into Python.          ██▓▒░
░▒▓██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄██▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
  ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒'''


def _TokensCollide(t1, t2):
  if not t1: return False
  colliding_tokens = {token.NAME, token.NUMBER, token.STRING, token.OP}
  if t1.type not in colliding_tokens or t2.type not in colliding_tokens:
    return False
  if t1.type == token.NAME and keyword.iskeyword(t1.string): return False
  if t2.type == token.NAME and keyword.iskeyword(t2.string): return False
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
      raise SyntaxError(f'Failed to parse ast from `{expstr}`'
                        f' when processing these chunks: {token_blocks}') from e
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


'''▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
░▒▓██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀██▓▒░
░▒▓██  Expression Evaluation:  Duct-taping Python expressions onto YAML.   ██▓▒░
░▒▓██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄██▓▒░
░▒▓██████████████████████████████████████████████████████████████████████████▓▒░
 ░▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░
  ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒'''

def _BuiltinFuncsMapper():
  def cond(condition, if_true, if_false):
    return if_true if condition else if_false
  return {
    'cond': cond,
  }
_BUILTIN_FUNCS = _BuiltinFuncsMapper()


_BUILTIN_NAMES = {
  'up': lambda ectx: ectx.scope._gcl_parent_ or ectx.Raise(ValueError,
                     f'No enclosing tuple (value to `up`) in this context.'),
  'super': lambda ectx: ectx.scope._gcl_super_ or ectx.Raise(ValueError,
                     f'No parent tuple (value to `super`) in this context.'),
}
_BUILTIN_VARS = {
  'external': external, 'null': null
}


def _GclNameLookup(name, ectx):
  if name in _BUILTIN_NAMES: return _BUILTIN_NAMES[name](ectx)
  if name in _BUILTIN_VARS: return _BUILTIN_VARS[name]
  if name in ectx.scope:
    get = ectx.scope._gcl_traceable_get_(name, ectx)
    if get is external:
      ectx.Raise(ValueError, f'`{name}` is external in this scope')
    if get is not null: return get
  if ectx.scope._gcl_parent_:
    with ectx.Scope(ectx.scope._gcl_parent_):
      return _GclNameLookup(name, ectx)
  if name in ectx.opts.globals: return ectx.opts.globals[name]
  mnv = ectx.opts.missing_name_value
  if mnv is not YamletOptions.Error: return mnv
  ectx.Raise(NameError, f'There is no variable called `{name}` in this scope.')


def _GclExprEval(expr, ectx):
  _DebugPrint(f'Evaluate: {expr}')
  chunks = _ParseIntoChunks(expr)
  vals = [_EvalGclAst(chunk, ectx) for chunk in chunks]
  if len(vals) == 1 and not isinstance(vals[0], GclDict): return vals[0]
  return _CompositeGclTuples(vals, ectx)


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
      if isinstance(val, GclDict):
        try: return val._gcl_traceable_get_(et.attr, ectx)
        except KeyError: ectx.Raise(KeyError, f'No {et.attr} in this scope.')
      return val[et.attr]
    case ast.BinOp:
      l, r = ev(et.left), ev(et.right)
      match type(et.op):
        case ast.Add: return l + r
      ectx.Raise(NotImplementedError, f'Unsupported binary operator `{et.op}`.')
    case ast.Compare:
      l = ev(et.left)
      for op, r in zip(et.ops, et.comparators):
        r = ev(r)
        match type(op):
          case ast.Eq:
            if l != r: return False
          case ast.NotEq:
            if l == r: return False
          case ast.Lt:
            if l >= r: return False
          case ast.LtE:
            if l > r: return False
          case ast.Gt:
            if l <= r: return False
          case ast.GtE:
            if l < r: return False
          case ast.Is:
            if l is not r: return False
          case ast.IsNot:
            if l is r: return False
          case ast.In:
            if l not in r: return False
          case ast.NotIn:
            if l in r: return False
          case _: ectx.Raise(NotImplementedError,
                             f'UnKnown comparison operator `{op}`.')
        l = r
      return True
    case ast.BoolOp:
      v = None
      match type(et.op):
        case ast.And:
          for v in et.values:
            v = ev(v)
            if not v: return v
        case ast.Or:
          for v in et.values:
            v = ev(v)
            if v: return v
        case _: ectx.Raise(NotImplementedError,
                           f'Unknown boolean operator `{op}`.')
      return v
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
    case ast.List:
      return [ev(x) for x in et.elts]
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
    if res: res = res.yamlet_clone(ectx.scope)
    else: res = ectx.NewGclDict()
    res.yamlet_merge(t, ectx)
  return res
