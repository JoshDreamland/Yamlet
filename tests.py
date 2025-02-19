#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import tempfile
import traceback
import unittest
import yamlet

from contextlib import contextmanager
from ruamel.yaml.constructor import ConstructorError


class RelativeStringValue(yamlet.Compositable):
  def __init__(self, loader_or_str, node_if_loader=None):
    if node_if_loader:
      self.val = str(loader_or_str.construct_scalar(node_if_loader))
    else:
      self.val = loader_or_str

  def yamlet_merge(self, other, ectx):
    if isinstance(other, str): self.val = f'{self.val} {other}'.strip()
    elif isinstance(other, RelativeStringValue):
      self.val = f'{self.val} {other.val}'.strip()
    else: ectx.Raise(
        f'Cannot composite {type(other).__name__} with RelativeStringValue')

  def yamlet_clone(self, other, ectx):
    return RelativeStringValue(self.val)

  def __eq__(self, other):
    if isinstance(other, str): return self.val == other
    return self.val == other.val

  def __repr__(self): return f'RelativeStringValue({self.val!r})'
  def __str__(self): return f'{self.val}'


def ParameterizedOnOpts(klass):
  YO = yamlet.YamletOptions
  YDO = yamlet._DebugOpts
  # Create cloned classes with different Opts
  def mkclass(name, caching_mode, preprocessing=None, traces=None):
    # Dynamically create a new class extending the input ("parameterized") class
    new_class = type(name, (klass,), {})

    debug = YDO(preprocessing=preprocessing, traces=traces)
    def Opts(self, **kwargs):
      return yamlet.YamletOptions(**kwargs, caching=caching_mode,
                                  _yamlet_debug_opts=debug)
    new_class.Opts = Opts
    return new_class

  # Generate the three versions of the class with different caching modes
  NoCacheClass = mkclass(f'{klass.__name__}_NoCaching', YO.CACHE_NOTHING)
  NormalCacheClass = mkclass(f'{klass.__name__}_DefCaching', YO.CACHE_VALUES)
  DebugCacheClass = mkclass(f'{klass.__name__}_DebugCaching',
                            YO.CACHE_DEBUG, traces=YDO.TRACE_PRETTY)
  DebugAllClass = mkclass(f'{klass.__name__}_PreprocessAll',
                          YO.CACHE_DEBUG, YDO.PREPROCESS_EVERYTHING)

  # Add the new classes to the global scope for unittest to pick up
  for test_derivative in [NoCacheClass, NormalCacheClass, DebugCacheClass]:
    globals()[test_derivative.__name__] = test_derivative
  return DebugAllClass


def DefaultConfigOnly(klass):
  def Opts(self, **kwargs): return yamlet.YamletOptions(**kwargs)
  klass.Opts = Opts
  return klass

def active(v):
  if not v: return False
  return v.lower() in {'on', 'yes', 'true', 'full'}

ParameterizedForStress = (
    ParameterizedOnOpts if active(os.getenv('yamlet_stress'))
    else DefaultConfigOnly)


@ParameterizedOnOpts
class TestTupleCompositing(unittest.TestCase):
  def test_composited_fields(self):
    YAMLET = '''# Yamlet
    t1:
      a:
        ab:
          aba: 121
          abc: 123
        ac:
          acc: 133
      c:
        cb:
          cba: 321
          cbb: bad value
    t2:
      b:
        bb:
          bba: 221
          bbb: 222
        bc:
          bca: 231
          bcc: 233
      c:
        ca:
          caa: 311
          cab: 312
          cac: 313
        cb:
          cbb: 322
          cbc: 323
        cc:
          cca: 331
          ccb: 332
          ccc: 333
    t3:
      a:
        aa:
          aaa: 111
          aab: 112
          aac: 113
        ab:
          abb: 122
        ac:
          aca: 131
          acb: 132
      b:
        ba:
          baa: 211
          bab: 212
          bac: 213
        bb:
          bbc: 223
        bc:
          bcb: 232
    comp1: !composite t1 t2 t3
    comp2: !composite
      - t1
      - t2 t3
    comp3: !expr t1 t2 t3
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    for compn in ['comp1', 'comp2', 'comp3']:
      self.assertTrue(compn in y)
      comp = y[compn]
      for k1, v1 in {'a': 100, 'b': 200, 'c': 300}.items():
        self.assertTrue(k1 in comp, f'{k1} in {compn}: {comp}')
        comp1 = comp[k1]
        for k2, v2 in {'a': 10, 'b': 20, 'c': 30}.items():
          self.assertTrue((k1 + k2) in comp1, f'{k1 + k2} in {compn}: {comp1}')
          comp2 = comp1[k1 + k2]
          for k3, v3 in {'a': 1, 'b': 2, 'c': 3}.items():
            self.assertTrue((k1 + k2 + k3) in comp2,
                            f'{k1 + k2 + k3} in {compn}: {comp2}')
            self.assertEqual(comp2[k1 + k2 + k3], v1 + v2 + v3)

  def test_partial_composition(self):
    YAMLET = '''# YAMLET
    t1:
      val:  world
      deferred: !fmt Hello, {val}!
    t2: !composite
      - t1
      - {
        val: all you happy people
      }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t1']['deferred'], 'Hello, world!')
    self.assertEqual(y['t2']['deferred'], 'Hello, all you happy people!')

  def test_parents_update(self):
    YAMLET = '''# YAMLET
    t1:
      sub:
        deferred: !fmt Hello, {val}!
    t2: !composite
      - t1
      - {
        val: world
      }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['sub']['deferred'], 'Hello, world!')

  def test_parents_update_2(self):
    '''Functions like the above test but also checks precedence.

    It's assumed that the desirable behavior is that all variables in descendent
    tuples take precedence over any values in the parent tuples. I left two
    tests because even if someone changes this behavior to give the parent
    priority, the above test should still pass.
    '''
    YAMLET = '''# YAMLET
    t1:
      val: doppelgänger
      sub:
        deferred: !fmt Hello, {val}!
    t2: !composite
      - t1
      - {
        val: world
      }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['sub']['deferred'], 'Hello, world!')

  def test_parents_update_3(self):
    YAMLET = '''# YAMLET
    t1:
      deferred: !fmt Hello, {val}!
    t2:
      val: world
      sub: !expr t1 {}
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['sub']['deferred'], 'Hello, world!')

  def test_parents_update_3b(self):
    YAMLET = '''# YAMLET
    t1:
      deferred: !fmt Hello, {val}!
    t2:
      val: world
      sub: !expr t1
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    with AssertRaisesCleanException(self, NameError):
      val = y['t2']['sub']['deferred']
      self.fail(f'Did not throw an exception; got `{val}`')

  def test_parents_update_4(self):
    YAMLET = '''# YAMLET
    t1:
      deferred: !fmt Hello, {val}!
    t2:
      val: world
      sub: !composite
        - t1
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['sub']['deferred'], 'Hello, world!')

  def test_compositing_in_parenths(self):
    YAMLET = '''# YAMLET
    t1:
      a: 10
      b: 10
      c: 30
    val: !expr |
        len(t1 {c: 30, d: 40, e:50})
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['val'], 5)

  def test_overriding_inherited_tuples(self):
    YAMLET = '''# YAMLET
    t1:
      shared_key: Value that appears in both tuples
      sub:
        t1_only_key: Value that only appears in t1
        t1_only_key2: Second value that only appears in t1
      sub2:
        shared_key2: Nested value in both

    t2: !composite
      - t1
      - t2_only_key: Value that only appears in t2
        sub: !expr |
            { t2_only_key2: 'Second value that only appears in t1' }
        sub2:
          t2_only_key3: Nested value only in t2
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t1']['shared_key'], 'Value that appears in both tuples')
    self.assertEqual(y['t2']['shared_key'], 'Value that appears in both tuples')
    self.assertEqual(y['t1']['sub'].keys(), {'t1_only_key', 't1_only_key2'})
    self.assertEqual(y['t2']['sub'].keys(), {'t2_only_key2'})
    self.assertEqual(y['t1']['sub2']['shared_key2'], 'Nested value in both')
    self.assertEqual(y['t2']['sub2']['shared_key2'], 'Nested value in both')
    self.assertEqual(y['t2']['sub2']['t2_only_key3'], 'Nested value only in t2')
    self.assertEqual(y['t1']['sub2'].keys(), {'shared_key2'})
    self.assertEqual(y['t2']['sub2'].keys(), {'shared_key2', 't2_only_key3'})

  def test_overriding_inherited_tuples_with_ugliness(self):
    YAMLET = '''# YAMLET
    t1:
      shared_key: Value that appears in both tuples
      sub:
        t1_only_key: Value that only appears in t1
        t1_only_key2: Second value that only appears in t1
      sub2:
        shared_key2: Nested value in both

    t2: !expr |
      t1 {
          t2_only_key: 'Value that only appears in t2',
          sub: [{
            t2_only_key2: 'Second value that only appears in t2'
          }][0],  # Trick to replace `sub` entirely
          sub2: {
            t2_only_key3: 'Nested value only in t2'
          }
      }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t1']['shared_key'], 'Value that appears in both tuples')
    self.assertEqual(y['t2']['shared_key'], 'Value that appears in both tuples')
    self.assertEqual(y['t1']['sub'].keys(), {'t1_only_key', 't1_only_key2'})
    self.assertEqual(y['t2']['sub'].keys(), {'t2_only_key2'})
    self.assertEqual(y['t1']['sub2']['shared_key2'], 'Nested value in both')
    self.assertEqual(y['t2']['sub2']['shared_key2'], 'Nested value in both')
    self.assertEqual(y['t2']['sub2']['t2_only_key3'], 'Nested value only in t2')
    self.assertEqual(y['t1']['sub2'].keys(), {'shared_key2'})
    self.assertEqual(y['t2']['sub2'].keys(), {'shared_key2', 't2_only_key3'})

  def test_nullification(self):
    YAMLET = '''# YAMLET
    t1:
      a: apple
      b: boy
      c: cat
      d: dog
    t2:
      b: !null
      c: !null
      d: !external
    t3: !expr t1 t2
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(len(y['t1']), 4)
    self.assertEqual(len(y['t2']), 3)
    self.assertEqual(len(y['t3']), 2)
    self.assertEqual(y['t3'], {'a': 'apple', 'd': 'dog'})

  def test_external_access(self):
    YAMLET = '''# YAMLET
    t1:
      v: value
      sub:
        v: !external
        exp: !expr v
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    with AssertRaisesCleanException(self, ValueError):
      val = y['t1']['sub']['exp']
      self.fail(f'Did not throw an exception; got `{val}`')

  def test_null_access(self):
    YAMLET = '''# YAMLET
    t1:
      v: value
      sub:
        v: !null
        exp: !expr v
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual( y['t1']['sub']['exp'], 'value')


@ParameterizedOnOpts
class TestInheritance(unittest.TestCase):
  def test_up_and_super(self):
    YAMLET = '''# Yamlet
    t1:
      a: one
      sub:
        a: two
    t2: !composite
      - t1
      - a: three
        sub:
          a: four
          counting: !fmt '{up.super.a} {super.a} {up.a} {a}'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['sub']['counting'], 'one two three four')

  def test_invalid_up_super_usage(self):
    YAMLET = '''# Yamlet
    t:
      a: !expr up.x
      x: an actual value
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    with AssertRaisesCleanException(self, KeyError):
        val = y['t']['a']
        self.fail(f'Did not throw an exception; got `{val}`')


@ParameterizedOnOpts
class TestValueMechanics(unittest.TestCase):
  def test_escaped_braces(self):
    YAMLET = '''# Yamlet
    v: Hello
    v2: world
    v3: !fmt '{{{v}}}, {{{{{v2}}}}}{{s}}!'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['v3'], '{Hello}, {{world}}{s}!')

  def test_array_comprehension(self):
    YAMLET = '''# Yamlet
    my_array: [1, 2, 'red', 'blue']
    fishes: !expr "['{x} fish' for x in my_array]"
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['fishes'], ['1 fish', '2 fish', 'red fish', 'blue fish'])

  def test_dict_comprehension(self):
    YAMLET = '''# Yamlet
    my_array: [1, 2, 'red', 'blue']
    fishes: !expr "{x: 'fish' for x in my_array}"
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['fishes'],
                     {1: 'fish', 2: 'fish', 'red': 'fish', 'blue': 'fish'})

  def test_array_comprehension_square(self):
    YAMLET = '''# Yamlet
    array1: [1, 2, 3, 4]
    array2: ['red', 'green', 'blue', 'yellow']
    fishes: !expr "['{x} {y} fish' for x in array1 for y in array2]"
    filtered: !expr |
        ['{x} {y} fish' for x in array1 for y in array2 if x != len(y)]
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    fishes = t['fishes']
    self.assertEqual(len(fishes), 16)
    self.assertEqual(fishes[0], '1 red fish')
    self.assertEqual(fishes[15], '4 yellow fish')
    filtered = t['filtered']
    self.assertEqual(len(filtered), 14)
    self.assertEqual(filtered, [
        '1 red fish', '1 green fish', '1 blue fish', '1 yellow fish',
        '2 red fish', '2 green fish', '2 blue fish', '2 yellow fish',
        '3 green fish', '3 blue fish', '3 yellow fish',
        '4 red fish', '4 green fish', '4 yellow fish'])

  def test_dict_literal(self):
    YAMLET = '''# Yamlet
    four: 4
    mydict: !expr |
      {1: 2, three: four}
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(set(t['mydict'].keys()), {1, 'three'})
    self.assertEqual(t['mydict'][1], 2)
    self.assertEqual(t['mydict']['three'], 4)

  def test_set_literal(self):
    YAMLET = '''# Yamlet
    four: 4
    myset: !expr |
      {1, 2, 'three', four}
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['myset'], {1, 2, 'three', 4})

  def test_pytuple_literal(self):
    YAMLET = '''# Yamlet
    four: 4
    my_python_tuple: !expr |
      (1, 2, 'three', four)
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['my_python_tuple'], (1, 2, 'three', 4))

  def test_string_from_up(self):
    YAMLET = '''# Yamlet
    val: 1337
    t:
      val2: !expr up.val
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['t']['val2'], 1337)

  def test_string_from_up_in_if(self):
    YAMLET = '''# Yamlet
    val: 1337
    !if 1:
      t:
        val2: !expr val
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['t']['val2'], 1337)

  def test_reference_other_scope(self):
    YAMLET = '''# Yamlet
    context:
      not_in_evaluating_scope: Hello, world!
      referenced: !fmt '{not_in_evaluating_scope}'
    result: !expr context.referenced
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['result'], 'Hello, world!')

  def test_reference_other_scope_2(self):
    YAMLET = '''# Yamlet
    context:
      not_in_evaluating_scope: Hello, world!
      referenced: !fmt '{not_in_evaluating_scope}'
    context2:
      inner_ref: !expr context
      referenced_2: !expr inner_ref.referenced
    result: !expr context2.referenced_2
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['result'], 'Hello, world!')

  def test_reference_env(self):
    YAMLET = '''# Yamlet
    other_context:
      not_inherited: Hello, world!
      referenced: !fmt '{not_inherited}'
    my_context:
      my_variable: !expr other_context.referenced
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['my_context']['my_variable'], 'Hello, world!')

  def test_reference_nested_env(self):
    YAMLET = '''# Yamlet
    other_context:
      not_inherited: Hello, world!
      subcontext:
        referenced: !fmt '{not_inherited}'
    my_context:
      captured_subcontext: !expr other_context.subcontext
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['my_context']['captured_subcontext']['referenced'],
                     'Hello, world!')

  def test_reference_nested_env_2(self):
    YAMLET = '''# Yamlet
    other_context:
      not_inherited: Hello, world!
      subcontext:
        referenced: !fmt '{not_inherited}'
    my_context:
      captured_subcontext: !composite
        - other_context.subcontext
        - red: herring
          not_inherited: 'Good night, moon!'
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['my_context']['captured_subcontext']['referenced'],
                     'Good night, moon!')

  def test_reference_nested_env_3(self):
    YAMLET = '''# Yamlet
    other_context:
      not_inherited: Hello, world!
      subcontext:
        referenced: !fmt '{not_inherited}'
    my_context:
      not_inherited: 'Good night, moon!'
      captured_subcontext: !composite
        - other_context.subcontext
        - red: herring
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['my_context']['captured_subcontext']['referenced'],
                     'Good night, moon!')

  def test_reference_nested_env_4(self):
    YAMLET = '''# Yamlet
    other_context:
      not_inherited: Hello, world!
      subcontext:
        referenced: !fmt '{not_inherited}'
    my_context:
      captured_subcontext: !composite
        - other_context.subcontext
        - red: herring
    test_probe: !expr my_context.captured_subcontext.super
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertTrue(t['test_probe'] is t['other_context']['subcontext'])
    self.assertEqual(t['my_context']['captured_subcontext']['referenced'],
                     'Hello, world!')

  def test_reference_nested_env_5(self):
    YAMLET = '''# Yamlet
    chain_1:
      not_inherited: Hello, world!
      subcontext:
        referenced: !fmt '{not_inherited}'
    chain_2:
      captured_subcontext_1: !composite
        - chain_1.subcontext
        - red: herring
    chain_3:
      captured_subcontext_2: !composite
        - chain_2.captured_subcontext_1
        - hoax: value
    chain_4:
      captured_subcontext_3: !composite
        - chain_3.captured_subcontext_2
        - artifice: more junk
    result: !fmt '{chain_4.captured_subcontext_3.referenced}'
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['result'], 'Hello, world!')


@ParameterizedOnOpts
class TestFunctions(unittest.TestCase):
  def test_escaped_braces(self):
    YAMLET = '''# Yamlet
    t:
      v: !expr func(x)
      w: !expr func('I am not called.')
      x: !expr func('Hello, ')
    '''
    side_effect = []
    uniq = ['world!']
    def func(x):
      side_effect.append(x)
      return uniq

    loader = yamlet.Loader(self.Opts(functions={'func': func}))
    y = loader.load(YAMLET)
    self.assertTrue(y['t']['v'] is uniq)
    self.assertEqual(side_effect, ['Hello, ', ['world!']])


@ParameterizedOnOpts
class TestConditionals(unittest.TestCase):
  def test_cond_routine(self):
    YAMLET = '''# Yamlet
    t1:
      color: !expr cond(blocked, 'red', 'green')
    t2: !composite
      - t1
      - { blocked: True }
    t3: !composite
      - t1
      - { blocked: False }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['color'], 'red')
    self.assertEqual(y['t3']['color'], 'green')

  def test_cond_routine_2(self):
    YAMLET = '''# Yamlet
    t1:
      conditionals: !expr |
        cond(blocked, {
          color: 'red'
        }, {
          color: 'green'
        }) {
          val: 'Color: {color}'
        }
    t2: !composite
      - t1
      - { blocked: True }
    t3: !composite
      - t1
      - { blocked: False }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['conditionals']['color'], 'red')
    self.assertEqual(y['t2']['conditionals']['val'], 'Color: red')
    self.assertEqual(y['t3']['conditionals']['val'], 'Color: green')
    self.assertEqual(y['t3']['conditionals']['color'], 'green')

  def test_if_statement_templating(self):
    YAMLET = '''# Yamlet
    t0:
      !if animal == 'fish':
        environment: water
      !elif animal == 'dog':
        attention: pats
        toys: !expr ([favorite_toy])
      !elif animal == 'cat':
        diet: meat
      !else:
        recommendation: specialist
    t1: !expr |
        t0 { animal: 'cat' }
    t2: !composite
      - t0
      - animal: dog
        favorite_toy: squeaky ball
        action: !expr attention
    t3: !expr |
        t0 { animal: 'fish' }
    t4: !expr |
        t0 { animal: 'squirrel' }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t1']['diet'], 'meat')
    self.assertEqual(y['t2']['action'], 'pats')
    self.assertEqual(y['t2']['attention'], 'pats')
    self.assertEqual(y['t2']['toys'], ['squeaky ball'])
    self.assertEqual(y['t3']['environment'], 'water')
    self.assertEqual(y['t4']['recommendation'], 'specialist')
    self.assertEqual(len(y['t1']), 2)
    self.assertEqual(len(y['t2']), 5)
    self.assertEqual(len(y['t3']), 2)
    self.assertEqual(len(y['t4']), 2)
    self.assertEqual(set(y['t1'].keys()), {'animal', 'diet'})
    self.assertEqual(set(y['t2'].keys()), {
        'animal', 'attention', 'toys', 'favorite_toy', 'action'})
    self.assertEqual(set(y['t3'].keys()), {'animal', 'environment'})
    self.assertEqual(set(y['t4'].keys()), {'animal', 'recommendation'})

  def test_if_statement_templating_2(self):
    YAMLET = '''# Yamlet
    t0:
      !if animal == 'fish':
        environment: water
      !elif animal == 'dog':
        attention: pats
        toys: !expr ([favorite_toy])
      !elif animal == 'cat':
        diet: meat
      !else:
        recommendation: specialist
    t1: !expr |
        t0 { animal: 'cat' }
    t2: !composite
      - t0
      - animal: dog
        favorite_toy: squeaky ball
        action: !expr attention
    t3: !expr |
        t0 { animal: 'fish' }
    t4: !expr |
        t0 { animal: 'squirrel' }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t1'].evaluate_fully(), {
        'animal': 'cat',
        'diet': 'meat'})
    self.assertEqual(y['t2'].evaluate_fully(), {
        'animal': 'dog',
        'action': 'pats',
        'attention': 'pats',
        'favorite_toy': 'squeaky ball',
        'toys': ['squeaky ball']})
    self.assertEqual(y['t3'].evaluate_fully(), {
        'animal': 'fish',
        'environment': 'water'})
    self.assertEqual(y['t4'].evaluate_fully(), {
        'animal': 'squirrel',
        'recommendation': 'specialist'})

  def test_if_statements(self):
    YAMLET = '''# Yamlet
    !if (1 + 1 == 2):
      a: 10
      b: { ba: 11 }
    !else:
      crap: value
    !if ('shark' == 'fish'):
      more-crap: values
    !elif ('crab' == 'crab'):
      b: { bb: 12 }
      c: 13
    !else:
      still-crap: 10
    !if ('fish' == 'fish'):
      d: 14
    !else:
      crapagain: 2
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertTrue('a' in y)
    self.assertTrue('b' in y)
    self.assertTrue('c' in y)
    self.assertTrue('d' in y)
    self.assertEqual(y['a'], 10)
    self.assertEqual(y['b']['ba'], 11)
    self.assertEqual(y['c'], 13)
    self.assertEqual(y['b']['bb'], 12)
    self.assertEqual(y['d'], 14)
    self.assertEqual(y.keys(), {'a', 'b', 'c', 'd'}, str(y))
    self.assertFalse('crap' in y)
    self.assertFalse('more-crap' in y)
    self.assertFalse('crapagain' in y)

  def test_buried_if(self):
    YAMLET = '''# Yamlet
    t:
      !if (1 + 1 == 2):
        a: 10
        b: { ba: 11 }
      !else:
        crap: value
      !if (2 + 2 == 6):
        crap: value
      !else:
        b: { bb: 12 }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertTrue('a' in y['t'])
    self.assertTrue('b' in y['t'])
    self.assertEqual(y['t']['a'], 10)
    self.assertEqual(y['t']['b']['ba'], 11)
    self.assertEqual(y['t']['b']['bb'], 12)
    self.assertEqual(y['t'].keys(), {'a', 'b'})
    self.assertFalse('crap' in y['t'])

  def test_nested_if_statements(self):
    # Another test from GPT, but this one, I asked for specifically. 😁
    YAMLET = '''# Yamlet
    t1:
      !if outer == 'A':
        !if inner == 'X':
          result: 'AX'
        !elif inner == 'Y':
          result: 'AY'
        !else:
          result: 'A?'
      !elif outer == 'B':
        !if inner == 'X':
          result: 'BX'
        !elif inner == 'Y':
          result: 'BY'
        !else :
          result: 'B?'
      !else:
        result: 'Unknown'
    t2: !expr |
        t1 { outer: 'A', inner: 'X' }
    t3: !expr |
        t1 { outer: 'A', inner: 'Z' }
    t4: !expr |
        t1 { outer: 'B', inner: 'Y' }
    t5: !expr |
        t1 { outer: 'B', inner: 'Z' }
    t6: !expr |
        t1 { outer: 'C', inner: 'X' }
    '''

    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)

    # Check for various nested conditions
    self.assertEqual(y['t2']['result'], 'AX')  # outer == 'A', inner == 'X'
    self.assertEqual(y['t3']['result'], 'A?')  # outer == 'A', inner not matched
    self.assertEqual(y['t4']['result'], 'BY')  # outer == 'B', inner == 'Y'
    self.assertEqual(y['t5']['result'], 'B?')  # outer == 'B', inner not matched
    self.assertEqual(y['t6']['result'], 'Unknown')  # outer not matched

  def test_double_nested_if_statements(self):
    YAMLET = '''# Yamlet
    one: 1
    tp:
      !if first == 'A':
        !if middle == 'X':
          !if last == 1:
            result: !fmt AX{one}
          !elif last == 2:
            result: AX2
          !else:
            result: AX?
        !elif middle == 'Y':
          !if last == 1:
            result: AY1
          !elif last == 2:
            result: AY2
          !else :
            result: AY?
        !else:
          result: 'A??'
      !elif first == 'B':
        !if middle == 'X':
          !if last == 1:
            result: BX1
          !elif last == 2:
            result: BX2
          !else :
            result: BX?
        !elif middle == 'Y':
          !if last == 1:
            result: BY1
          !elif last == 2:
            result: BY2
          !else:
            result: BY?
        !else:
          result: 'B??'
      !else:
        result: '???'
    ax1: !composite [tp, {first: 'A', middle: 'X', last: 1}]
    ax2: !composite [tp, {first: 'A', middle: 'X', last: 2}]
    ax3: !composite [tp, {first: 'A', middle: 'X', last: 3}]
    ay1: !composite [tp, {first: 'A', middle: 'Y', last: 1}]
    ay2: !composite [tp, {first: 'A', middle: 'Y', last: 2}]
    ay3: !composite [tp, {first: 'A', middle: 'Y', last: 3}]
    az1: !composite [tp, {first: 'A', middle: 'Z', last: 1}]
    bx1: !composite [tp, {first: 'B', middle: 'X', last: 1}]
    bx2: !composite [tp, {first: 'B', middle: 'X', last: 2}]
    bx3: !composite [tp, {first: 'B', middle: 'X', last: 3}]
    by1: !composite [tp, {first: 'B', middle: 'Y', last: 1}]
    by2: !composite [tp, {first: 'B', middle: 'Y', last: 2}]
    by3: !composite [tp, {first: 'B', middle: 'Y', last: 3}]
    bz1: !composite [tp, {first: 'B', middle: 'Z', last: 1}]
    cx1: !composite [tp, {first: 'C', middle: 'X', last: 1}]
    '''

    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)

    # Check for various nested conditions
    self.assertEqual(y['ax1']['result'], 'AX1')
    self.assertEqual(y['ax2']['result'], 'AX2')
    self.assertEqual(y['ax3']['result'], 'AX?')
    self.assertEqual(y['ay1']['result'], 'AY1')
    self.assertEqual(y['ay2']['result'], 'AY2')
    self.assertEqual(y['ay3']['result'], 'AY?')
    self.assertEqual(y['az1']['result'], 'A??')
    self.assertEqual(y['bx1']['result'], 'BX1')
    self.assertEqual(y['bx2']['result'], 'BX2')
    self.assertEqual(y['bx3']['result'], 'BX?')
    self.assertEqual(y['by1']['result'], 'BY1')
    self.assertEqual(y['by2']['result'], 'BY2')
    self.assertEqual(y['by3']['result'], 'BY?')
    self.assertEqual(y['bz1']['result'], 'B??')
    self.assertEqual(y['cx1']['result'], '???')

  def test_fuzzy_if(self):
    YAMLET = '''# Yamlet
    !if fuzzy == 'rodent':
      food: pellet
      !if fuzzy == 'hamster':
        habitat: tubes
    !elif fuzzy == 'fish':
      food: flake
    !else:
      food: kibble
    '''
    fuzzy = FuzzyAnimalComparator()
    loader = yamlet.Loader(self.Opts(globals={'fuzzy': fuzzy}))

    fuzzy.animal = 'hamster'
    y = loader.load(YAMLET)
    self.assertEqual(y.keys(), {'food', 'habitat'})
    self.assertEqual(y['food'], 'pellet')
    self.assertEqual(y['habitat'], 'tubes')

    fuzzy.animal = 'betta'
    y = loader.load(YAMLET)
    self.assertEqual(y.keys(), {'food'})
    self.assertEqual(y['food'], 'flake')

    fuzzy.animal = 'dog'
    y = loader.load(YAMLET)
    self.assertEqual(y.keys(), {'food'})
    self.assertEqual(y['food'], 'kibble')

    fuzzy.animal = 'rat'
    y = loader.load(YAMLET)
    self.assertEqual(y['food'], 'pellet')
    self.assertEqual(y.keys(), {'food'})

  def test_local_in_if(self):
    YAMLET = '''# Yamlet
    !if 1 + 1 == 2:
      !local my_var: Hello
    v: !fmt '{my_var}, world!'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['v'], 'Hello, world!')
    self.assertEqual(y.evaluate_fully(), {'v': 'Hello, world!'})

  def test_local_outside_if(self):
    YAMLET = '''# Yamlet
    !local my_var: oops
    !if 1 + 1 == 2:
      my_var: Hello
    v: !fmt '{my_var}, world!'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['v'], 'Hello, world!')
    self.assertEqual(y.evaluate_fully(), {'v': 'Hello, world!'})

  def test_local_inside_and_outside_if(self):
    YAMLET = '''# Yamlet
    !local my_var: oops
    !if 1 + 1 == 2:
      !local my_var: Hello
    v: !fmt '{my_var}, world!'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['v'], 'Hello, world!')
    self.assertEqual(y.evaluate_fully(), {'v': 'Hello, world!'})

  def test_nonlocal_outside_if(self):
    YAMLET = '''# Yamlet
    my_var: oops
    !if 1 + 1 == 2:
      !local my_var: Hello
    v: !fmt '{my_var}, world!'
    '''
    with self.assertRaises(ConstructorError):
      loader = yamlet.Loader(self.Opts())
      y = loader.load(YAMLET)
      self.assertEqual(y['v'], 'Hello, world!')
      self.assertEqual(y.evaluate_fully(), {'v': 'Hello, world!'})

  def test_get_from_if(self):
    YAMLET = '''# Yamlet
    !if 1 + 1 == 2:
      !local my_var: Hello
    v: !fmt '{my_var}, world!'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y.get('v', 'oops!'), 'Hello, world!')


@ParameterizedForStress
class TestStress(unittest.TestCase):
  def test_utter_insanity(self):
    YAMLET = '''# Yamlet
    name_number:
      !if number > 1000:
        name: !fmt '{lead.name} thousand{space}{remainder.name}'
        lead: !expr |
            name_number { number: up.number // 1000 }
        space: !expr cond(lead and remainder.name, ' ', '')
        remainder: !expr |
            name_number { number: up.number % 1000 }
      !elif number > 100:
        name: !fmt '{lead.name} hundred{space}{remainder.name}'
        lead: !expr |
            name_number { number: up.number // 100 }
        space: !expr cond(lead and remainder.name, ' ', '')
        remainder: !expr |
            name_number { number: up.number % 100 }
      !elif number > 19:
        name: !fmt '{lead}{hyphen}{remainder.name}'
        lead: !expr |
            ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty',
            'seventy', 'eighty', 'ninety'][int(number / 10)]  # Just2B different
        hyphen: !expr cond(lead and remainder.name, '-', '')
        remainder: !expr |
            name_number { number: up.number % 10 }
      !else:
        name: !expr |
            ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
             'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen',
             'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'][number]
    val: !expr |
        name_number { number: 236942 }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['val']['name'], 'two hundred thirty-six thousand nine hundred forty-two')


class FuzzyAnimalComparator:
  KINDS = {'hamster': 'rodent', 'rat': 'rodent', 'betta': 'fish', 'dog': 'dog'}
  def __init__(self, animal=None): self.animal = animal
  def __eq__(self, other):
    oa = other.animal if isinstance(other, FuzzyAnimalComparator) else other
    return self.animal == oa or (
        self.KINDS.get(self.animal) == oa or self.KINDS.get(oa) == self.animal)


class AssertRaisesCleanException:
  def __init__(self, tester, exc_tp, min_context=15, max_context=30):
    self.tester = tester
    self.exc_tp = exc_tp
    self.ex = None
    self.val = None
    self.min_context = min_context
    self.max_context = max_context

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    if exc_type is None:  # No exception was raised
      self.tester.fail('Did not throw an exception.')
      return False

    if not issubclass(exc_type, self.exc_tp):
      # Let other exceptions pass through
      return False

    format_exc = traceback.format_exception(exc_type, exc_value, exc_traceback)
    cut_from = 0
    for i, line in enumerate(format_exc):
      if ("The above exception was the direct cause of the following exception:"
          in line or
          "During handling of the above exception, another exception occurred:"
          in line): cut_from = i + 1
    ex = ''.join(format_exc[cut_from:])
    tb = traceback.format_tb(exc_traceback)

    exlines = ex.splitlines()
    fex = '  > ' + '\n  > '.join('\n'.join(exlines).splitlines())
    if len(tb) >= 3:
      raise AssertionError(f'Stack trace is ugly:\n{fex}\n'
                           f'The above exception should have had {3} '
                           f'calls on the stack, but had {len(tb)}.') from None
    if len(exlines) <= self.min_context:
      raise AssertionError(f'Yamlet trace is too small:\n{fex}\n'
                           f'The above exception should have been at least '
                           f'{self.min_context} lines, but was {len(exlines)}.'
      ) from None
    if len(exlines) >= self.max_context:
      raise AssertionError(f'Yamlet trace is too large:\n{fex}\n'
                           f'The above exception should have been at most '
                           f'{self.max_context} lines, but was {len(exlines)}.'
      ) from None

    # Suppress the exception (so it won't propagate)
    return True


@ParameterizedOnOpts
class TestFlatCompositing(unittest.TestCase):
  def test_specializing_conditions(self):
    YAMLET = '''# Yamlet
    tp:
      variable: defaulted value
      switch: off
      !if switch == 'on':
        variable: specialized value
    boring: !expr tp
    flashy: !expr tp {switch:'on'}
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['tp']['variable'], 'defaulted value')
    self.assertEqual(y['flashy']['variable'], 'specialized value')
    self.assertEqual(y['boring']['variable'], 'defaulted value')

  def test_specializing_conditions_2(self):
    YAMLET = '''# Yamlet
    tp:
      variable: !rel defaulted value
      switch: off
      !if switch == 'on':
        variable: !rel specialized value
    boring: !expr tp
    flashy: !expr tp {switch:'on'}
    '''
    ctors = {'!rel': RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    y = loader.load(YAMLET)
    self.assertEqual(y['tp']['variable'], 'defaulted value')
    self.assertEqual(y['flashy']['variable'], 'defaulted value specialized value')
    self.assertEqual(y['boring']['variable'], 'defaulted value')

  def test_specializing_conditions_3(self):
    YAMLET = '''# Yamlet
    tp:
      variable: !rel defaulted value
      switch: off
      !if switch == 'on':
        variable: !rel specialized value
      variable: !rel more defaulted value
    boring: !expr tp
    flashy: !expr tp {switch:'on'}
    '''
    ctors = {'!rel': RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    y = loader.load(YAMLET)
    self.assertEqual(y['tp']['variable'],
                     'defaulted value more defaulted value')
    self.assertEqual(y['flashy']['variable'],
                     'defaulted value specialized value more defaulted value')
    self.assertEqual(y['boring']['variable'],
                     'defaulted value more defaulted value')

  def test_specializing_conditions_non_relative_error(self):
    '''As of Yamlet 0.5, it is only considered an error if a composite operation
    is performed on a mixture of compositable and non-compositable values.
    This test mashes a non-compositable string value onto `variable` after
    setting it to something compositable and amending it in an conditional.'''
    YAMLET = '''# Yamlet
    tp:
      variable: !rel defaulted value
      switch: off
      !if switch == 'on':
        variable: !rel specialized value
      variable: colliding non-compositable value
    '''
    ctors = {'!rel': RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    with self.assertRaises(ConstructorError):
      y = loader.load(YAMLET)

  def test_specializing_conditions_non_relative_error_2(self):
    '''As of Yamlet 0.5, it is only considered an error if a composite operation
    is performed on a mixture of compositable and non-compositable values.
    This test only introduces a non-compositable value in the true branch of
    a conditional, so only that expression should error.'''
    YAMLET = '''# Yamlet
    tp:
      variable: !rel defaulted value
      switch: off
      !if switch == 'on':
        variable: colliding non-compositable value
      variable: !rel another compositable value
    boring: !expr tp
    explosive: !expr tp {switch:'on'}
    '''
    ctors = {'!rel': RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    y = loader.load(YAMLET)
    self.assertEqual(y['tp']['variable'],
                     'defaulted value another compositable value')
    self.assertEqual(y['boring']['variable'],
                     'defaulted value another compositable value')
    with AssertRaisesCleanException(self, ValueError):
      val = y['explosive']['variable']
      self.fail(f'Did not throw an exception; got `{val}`')

  def test_specializing_conditions_non_relative_allowed(self):
    '''Overriding a non-compositable value with a conditional is always allowed.
    '''
    YAMLET = '''# Yamlet
    tp:
      variable: defaulted value
      switch: off
      !if switch == 'on':
        variable: overriding value
    boring: !expr tp
    zesty: !expr tp {switch:'on'}
    '''
    ctors = {'!rel': RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    y = loader.load(YAMLET)
    self.assertEqual(y['tp']['variable'], 'defaulted value')
    self.assertEqual(y['boring']['variable'], 'defaulted value')
    self.assertEqual(y['zesty']['variable'], 'overriding value')

  def test_specializing_conditions_non_relative_allowed_2(self):
    '''Don't allow flat strings after an if-else ladder.'''
    YAMLET = '''# Yamlet
    tp:
      variable: defaulted value
      switch: off
      !if switch == 'on':
        variable: overriding value
      variable: completely clobbering value
    '''
    ctors = {'!rel': RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    with self.assertRaises(ConstructorError):
      y = loader.load(YAMLET)


@ParameterizedOnOpts
class TestRecursion(unittest.TestCase):
  def test_recursion(self):
    YAMLET = '''# Yamlet
    recursive:
      a: !expr b
      b: !expr a
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    with AssertRaisesCleanException(self, RecursionError):
      val = y['recursive']['a']
      self.fail(f'Did not throw an exception; got `{val}`')

  def test_if_directive_recursion(self):
    '''This is gonna break a lot of people's minds and spirits.'''
    YAMLET = '''# Yamlet
    parent:
      !if childvalue == 1:
        parentvalue: 'red'
      !else :
        parentvalue: 'blue'
    child: !expr |
      parent {
        childvalue: parentvalue != 'blue'
      }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    with AssertRaisesCleanException(self, RecursionError, max_context=40):
      val = y['child']['parentvalue']
      self.fail(f'Did not throw an exception; got `{val}`')


@ParameterizedOnOpts
class TestExpressionMechanics(unittest.TestCase):
  def test_unary_operators(self):
    YAMLET = '''# Yamlet
    add: !expr +10
    sub: !expr -10
    not: !expr not 10
    neg: !expr ~10
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['add'], 10)
    self.assertEqual(y['sub'], -10)
    self.assertEqual(y['not'], False)
    self.assertEqual(y['neg'], ~10)

  def test_binary_operators(self):
    YAMLET = '''# Yamlet
    add:  !expr 10 + 89
    sub:  !expr 89 - 10
    mul:  !expr 12 * 12
    div:  !expr 990 / 11
    idiv: !expr 995 // 11
    mod:  !expr 995 % 11
    band: !expr 0xFF & 0x1F7
    bor:  !expr 0xFF | 0x1F7
    xor:  !expr 0xFF ^ 0x1F7
    lsh:  !expr 0x1F7 << 4
    rsh:  !expr 0x1F7 >> 4
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['add'],  10 + 89)
    self.assertEqual(y['sub'],  89 - 10)
    self.assertEqual(y['mul'],  12 * 12)
    self.assertEqual(y['div'],  990 / 11)
    self.assertEqual(y['idiv'], 995 // 11)
    self.assertEqual(y['mod'],  995 % 11)
    self.assertEqual(y['band'], 0xFF & 0x1F7)
    self.assertEqual(y['bor'],  0xFF | 0x1F7)
    self.assertEqual(y['xor'],  0xFF ^ 0x1F7)
    self.assertEqual(y['lsh'],  0x1F7 << 4)
    self.assertEqual(y['rsh'],  0x1F7 >> 4)

  def test_fstring_concatenation(self):
    YAMLET = '''# Yamlet
    foo: Foo
    bar: Bar
    foobar: !expr f'{foo}{bar}'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['foobar'], 'FooBar')


@ParameterizedOnOpts
class TestNameLookupMechanics(unittest.TestCase):
  def test_xscope_up_mechanics(self):  # TODO: Check this against JSonnet
    YAMLET = '''# Yamlet               I think "erroneous value" is incorrect
    captured:
      value: permanent value
      nested:
        test_value: !expr up.value
    test_outer: !expr |
        captured { value: 'overridden value' }
    test_inner:
      value: erroneous value
      nested: !expr captured.nested {}
    test_direct: !expr captured.nested
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['test_direct']['test_value'], 'permanent value')
    self.assertEqual(y['test_outer']['nested']['test_value'], 'overridden value')
    self.assertEqual(y['test_inner']['nested']['test_value'], 'erroneous value')

  def test_local_in_up_scope(self):
    YAMLET = '''# Yamlet
    !local ARBITRARY_VALUES_TUPLE:
      MY_VAR: 'Hello, world!'
    !local CORRECT_VARIABLES_TUPLE:
      MY_VAR: !expr ARBITRARY_VALUES_TUPLE.MY_VAR
    variables: !expr CORRECT_VARIABLES_TUPLE
    '''
    loader = yamlet.Loader(self.Opts(globals={'target_platform': 'windows', 'OPTMODE': 'optimize'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['variables'].get('MY_VAR', 'oops!'), 'Hello, world!')


@ParameterizedOnOpts
class TestMergeMechanics(unittest.TestCase):
  """
  def test_merging_if_ladders(self):
    YAMLET = '''# Yamlet
    merge_one:
      !if 1 + 1 == 2:
        variable: Good night
      !else:
        phrase: !fmt '{variable}, moon!'
    merge_two:
      !if 1 + 1 == 4:
        variable: What up
      !else:
        phrase: !fmt '{variable}, world!'
    merged: !composite
    - merge_one
    - merge_two
    - variable: Hello
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['merged']['phrase'], 'Hello, world!')
"""
  def test_merging_relatives_in_ifs(self):
    YAMLET = '''# Yamlet
    merge_one:
      !if 1 + 1 == 2:
        variable: !rel Hello,
    merge_two:
      !if 2 + 2 == 4:
        variable: !rel world!
    merged: !composite
    - merge_one
    - merge_two
    '''
    ctors = {'!rel': RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    y = loader.load(YAMLET)
    self.assertEqual(y['merge_one']['variable'], 'Hello,')
    self.assertEqual(y['merge_two']['variable'], 'world!')
    self.assertEqual(y['merged']['variable'], 'Hello, world!')

  def test_merging_relatives_with_module_locals(self):
    YAMLET = '''# Yamlet
    other_file: !import other_file.yaml
    merge_one:
      !if 1 + 1 == 2:
        variable: !rel:expr other_file.module_global_wrapper
    merge_two:
      !if 2 + 2 == 4:
        variable: !rel world!
    merged: !composite
    - merge_one
    - merge_two
    '''
    memfile = '''# Yamlet
    module_global_wrapper: !fmt '{module_global},'
    '''
    loader = yamlet.Loader(self.Opts(
        import_resolver=TempFileRetriever({
            'other_file.yaml': TempModule(memfile, {'module_global': 'Hello'}),
        }), globals={'module_global': 'Goodbye'}))
    loader.add_constructor('!rel', RelativeStringValue,
                           style=yamlet.ConstructStyle.FMT)
    y = loader.load(YAMLET)
    self.assertEqual(y['merged']['variable'], 'Hello, world!')


class TempModule:
  def __init__(self, content, module_vars=None):
    if isinstance(content, TempModule):
      assert not module_vars
      content, module_vars = content.content, content.module_vars
    self.content, self.module_vars = content, module_vars or {}


def TempFileRetriever(files):
  def resolve_import(filename):
    f = files.get(filename)
    if not f: raise FileNotFoundError(f'No file `{filename}` registered')
    if isinstance(f, yamlet.ImportInfo): return f
    tm = TempModule(f)
    with tempfile.NamedTemporaryFile(mode='w+t', delete=False) as tf:
      tf.write(tm.content)
      res = yamlet.ImportInfo(tf.name, module_vars=tm.module_vars)
      files[f] = res
      return res
  return resolve_import


@ParameterizedOnOpts
class CrossModuleMechanics(unittest.TestCase):
  def test_module_globals(self):
    YAMLET = '''# Yamlet
    ext1: !import test_file_1
    ext2: !import test_file_2
    ubiquitous_global: dest-scoped value
    dest_only_global: 'Cool beans'
    ext1_local:       !expr ext1.tup.ref_local
    ext1_ubiquitous:  !expr ext1.tup.ref_ubiquitous_global
    ext1_destonly:    !expr ext1.tup.ref_dest_global
    ext1_module:      !expr ext1.tup.ref_module_global
    ext2_module:      !expr ext2.tup.ref_module_global
    ext1_tup: !expr ext1.tup {}
    ext2_tup: !expr ext2.tup {}
    '''
    memfile = '''# Yamlet
    my_own_var: Good night, moon!
    ubiquitous_global: module-scoped value
    tup:
      ref_local: !expr my_own_var
      ref_ubiquitous_global: !expr ubiquitous_global
      ref_module_global: !expr module_specific_global
      ref_dest_global: !expr dest_only_global
    '''
    loader = yamlet.Loader(self.Opts(import_resolver=TempFileRetriever({
        'test_file_1': TempModule(memfile, {'module_specific_global': 'msg1'}),
        'test_file_2': TempModule(memfile, {'module_specific_global': 'msg2'}),
    }), globals={'module_specific_global': 'the catch-all'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['ext1_local'], 'Good night, moon!')
    self.assertEqual(y['ext1_ubiquitous'], 'module-scoped value')
    self.assertEqual(y['ext1_destonly'], 'Cool beans')
    self.assertEqual(y['ext1_module'], 'msg1')
    self.assertEqual(y['ext2_module'], 'msg2')
    self.assertEqual(y['ext1_tup']['ref_local'], 'Good night, moon!')
    self.assertEqual(y['ext1_tup']['ref_ubiquitous_global'], 'dest-scoped value')
    self.assertEqual(y['ext1_tup']['ref_dest_global'], 'Cool beans')
    self.assertEqual(y['ext1_tup']['ref_module_global'], 'msg1')
    self.assertEqual(y['ext2_tup']['ref_module_global'], 'msg2')

  def test_module_globals_three_hops(self):
    YAMLET = '''# Yamlet
    ex_local: Goodbye
    import1: !import file1
    middle_local:  !fmt '{import1.ref_local}, world!'
    middle_global: !fmt '{import1.ref_global}, moon!'
    '''
    memfile1 = '''# Yamlet
    ex_local: Hello
    import2: !import file2
    ref_local:  !expr import2.ref_local
    ref_global: !expr import2.ref_global
    '''
    memfile2 = '''# Yamlet
    ref_local:  !expr ex_local
    ref_global: !expr ex_global
    '''
    loader = yamlet.Loader(self.Opts(import_resolver=TempFileRetriever({
        'file1': TempModule(memfile1, {'ex_global': 'Good night'}),
        'file2': TempModule(memfile2),
    }), globals={'ex_global': 'Smeg off'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['middle_local'], 'Hello, world!')
    self.assertEqual(y['middle_global'], 'Good night, moon!')

  def test_module_globals_three_hops_with_dot_lookup_in_first_hop(self):
    YAMLET = '''# Yamlet
    import1: !import 'memfile1'
    value:   !fmt '{import1.variables.ref_global}'
    '''
    memfile1 = '''# Yamlet
    variables: !import 'memfile2'
    '''
    memfile2 = '''# Yamlet
    ref_global: !fmt '{COMPILER_ROOT}'
    '''
    loader = yamlet.Loader(self.Opts(
        import_resolver=TempFileRetriever({
            'memfile1': TempModule(memfile1, {'COMPILER_ROOT': 'GoodValue'}),
            'memfile2': TempModule(memfile2),
        }), globals={
            'COMPILER_ROOT': 'BadValue',
        }))
    y = loader.load(YAMLET)
    self.assertEqual(y['value'], 'GoodValue')


@ParameterizedOnOpts
class GptsTestIdeas(unittest.TestCase):
  def test_chained_up_super(self):
    YAMLET = '''# Yamlet
    t1:
      a: base
      sub:
        a: level1
        subsub:
          a: level2
    t2: !composite
      - t1
      - sub:
          subsub:
            a: override
            test: !fmt '{up.up.super.a} {up.a} {super.a} {a}'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t2']['sub']['subsub']['test'],
                    'base level1 level2 override')

  def test_nested_nullification(self):
    YAMLET = '''# Yamlet
    t1:
      a: apple
      b: boy
      sub:
        c: cat
        d: dog
    t2:
      a: !null
      sub:
        d: !null
    t3: !expr t1 t2
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertFalse(isinstance(y['t3']['sub'], yamlet.DeferredValue))
    self.assertEqual(y['t3'], {'b': 'boy', 'sub': {'c': 'cat'}})

  def test_nested_super_override(self):
    YAMLET = '''# Yamlet
    t1:
      a: original
      sub:
        a: intermediate
        subsub:
          a: final
          result: !fmt '{up.a} {up.up.a} {a}'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t1']['sub']['subsub']['result'], 'intermediate original final')

  def test_invalid_up_usage(self):
    YAMLET = '''# Yamlet
    a: !expr up.a
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    with AssertRaisesCleanException(self, ValueError):
        val = y['a']
        self.fail(f'Did not throw an exception; got `{val}`')

  def test_invalid_super_usage(self):
    YAMLET = '''# Yamlet
    t1:
      a: some value
      sub:
        a: !expr super.a
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    with AssertRaisesCleanException(self, ValueError):
        val = y['t1']['sub']['a']
        self.fail(f'Did not throw an exception; got `{val}`')


@ParameterizedOnOpts
class RunExample(unittest.TestCase):
  def test_main_yamlet_example(self):
    loader = yamlet.Loader(self.Opts(functions={'now': lambda: 'now o\'clock'}))
    t = loader.load_file('yaml-gcl.yaml')
    self.assertEqual(t['childtuple']['coolbeans'], 'Hello, world! I say cooool beans!')
    self.assertEqual(t['childtuple2']['coolbeans'], 'Hello, world! I say awesome sauce!')

    # Didn't I tell you not to do this?
    self.assertEqual(t['horribletuple']['coolbeans'], 'Hello, world! I say cooool sauce!')
    self.assertEqual(t['horribletuple2']['coolbeans'], 'Hello, world! I say awesome beans!')

    self.assertEqual(t['other_features']['timestamp'], 'now o\'clock')
    self.assertEqual(t['other_features']['two'], 2)

    self.assertEqual(t['c1']['value'], 'You chose the first option.')
    self.assertEqual(t['c2']['value'], 'You chose the second option.')
    self.assertEqual(t['c3']['value'], 'You chose some other option.')

    # The following would break because of cycles.
    # print(t['recursive']['a'])

    def assertLenGreater(x, l): self.assertGreater(len(x), l, f'Length of: {x}')
    assertLenGreater(t['childtuple'].explain_value('coolbeans'), 50)
    assertLenGreater(t['childtuple'].explain_value('beans'),  50)
    assertLenGreater(t['childtuple2'].explain_value('beans'), 50)

  def test_top_example_from_the_readme(self):
    YAMLET = '''# Yamlet
    key1: my common value
    key2: !expr key1 + ' my extra specialized value'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['key2'], 'my common value my extra specialized value')

  def test_platform_example_from_the_readme(self):
    YAMLET = '''# Yamlet
    !if platform == 'Windows':
      directory_separator: \\
      executable_extension: exe
      dylib_extension: dll
    !elif platform == 'Linux':
      directory_separator: /
      executable_extension: null
      dylib_extension: so
    !else:
      directory_separator: /
      executable_extension: bin
      dylib_extension: dylib
    '''
    loader = yamlet.Loader(self.Opts(globals={'platform': 'Windows'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['directory_separator'], '\\')
    self.assertEqual(y['executable_extension'], 'exe')
    self.assertEqual(y['dylib_extension'], 'dll')

    loader = yamlet.Loader(self.Opts(globals={'platform': 'Linux'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['directory_separator'], '/')
    self.assertEqual(y['executable_extension'], None)
    self.assertEqual(y['dylib_extension'], 'so')

    loader = yamlet.Loader(self.Opts(globals={'platform': 'Who knows'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['directory_separator'], '/')
    self.assertEqual(y['executable_extension'], 'bin')
    self.assertEqual(y['dylib_extension'], 'dylib')

  def test_yamlet_mapping_example_from_the_readme(self):
    YAMLET = '''# Yamlet
    my_yamlet_map: !expr |
      {
        key: 'my string value with {inlined} {expressions}',
        otherkey: 'my other value'
      }
    '''
    loader = yamlet.Loader(self.Opts(globals={
        'inlined': 'inlined', 'expressions': 'expressions'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['my_yamlet_map']['key'],
                     'my string value with inlined expressions')
    self.assertEqual(y['my_yamlet_map']['otherkey'], 'my other value')

  def test_string_formatting_examples_from_the_readme(self):
    YAMLET = '''# Yamlet
    subject: world
    str1: !expr ('Hello, {subject}!')
    str2: !expr ('Hello, ' + subject + '!')
    str3: !fmt 'Hello, {subject}!'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['str1'], 'Hello, world!')
    self.assertEqual(y['str2'], 'Hello, world!')
    self.assertEqual(y['str3'], 'Hello, world!')

  def test_composition_examples_from_the_readme(self):
    YAMLET = '''# Yamlet
    parent_tuple:
      old_key: old value
    child_tuple_A: !expr |
      parent_tuple {
        new_key: 'new value',  # Python dicts and YAML flow mappings...
        old_key: 'new overriding value',  # String values must be quoted...
      }
    child_tuple_B: !composite
      - parent_tuple  # The raw name of the parent tuple to composite
      - new_key: new value  # This is a mapping block inside a sequence block!
        old_key: new overriding value  # Note that normal YAML `k: v` is fine.
    child_tuple_C: !composite
      - parent_tuple  # The raw name of the parent tuple to composite
      - {
        new_key: new value,  # A comma is now required here!
        old_key: new overriding value  # Plain style is still allowed.
      }
    '''
    loader = yamlet.Loader(self.Opts(globals={
        'inlined': 'inlined', 'expressions': 'expressions'}))
    y = loader.load(YAMLET)
    self.assertEqual(y['child_tuple_A']['new_key'], 'new value')
    self.assertEqual(y['child_tuple_A']['old_key'], 'new overriding value')
    self.assertEqual(y['child_tuple_B']['new_key'], 'new value')
    self.assertEqual(y['child_tuple_B']['old_key'], 'new overriding value')
    self.assertEqual(y['child_tuple_C']['new_key'], 'new value')
    self.assertEqual(y['child_tuple_C']['old_key'], 'new overriding value')

  def test_fruit_example_from_the_readme(self):
    YAMLET = '''# Yamlet
    tuple_A:
      fruit: Apple
      tuple_B:
        fruit: Banana
        value: !fmt '{up.fruit} {fruit}'
    tuple_C: !expr |
      tuple_A {
        tuple_B: {
          fruit: 'Blueberry',
          value2: '{super.up.fruit} {super.fruit} {fruit} {up.fruit}',
          value3: '{super.value}  -vs-  {value}',
        },
        fruit: 'Cherry'
      }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['tuple_A']['fruit'], 'Apple')
    self.assertEqual(y['tuple_A']['tuple_B']['fruit'], 'Banana')
    self.assertEqual(y['tuple_C']['fruit'], 'Cherry')
    self.assertEqual(y['tuple_C']['tuple_B']['fruit'], 'Blueberry')

    self.assertEqual(y['tuple_A']['tuple_B']['value'], 'Apple Banana')
    self.assertEqual(y['tuple_C']['tuple_B']['value2'],
                     'Apple Banana Blueberry Cherry')
    self.assertEqual(y['tuple_C']['tuple_B']['value3'],
                     'Apple Banana  -vs-  Cherry Blueberry')
    self.assertEqual(y['tuple_C']['tuple_B']['value'], 'Cherry Blueberry')

  def test_lambda_example_from_the_readme(self):
    YAMLET = '''# Yamlet
    add_two_numbers: !lambda |
                     x, y: x + y
    name_that_shape: !lambda |
       x: cond(x < 13, ['point', 'line', 'plane', 'triangle',
               'quadrilateral', 'pentagon', 'hexagon', 'heptagon', 'octagon',
               'nonagon', 'decagon', 'undecagon', 'dodecagon'][x], '{x}-gon')
    is_thirteen: !lambda |
                 x: 'YES!!!' if x is 13 else 'no'
    five_plus_seven:      !expr add_two_numbers(5, 7)
    shape_with_4_sides:   !expr name_that_shape(4)
    shape_with_14_sides:  !expr name_that_shape(14)
    seven_is_thirteen:    !expr is_thirteen(7)
    thirteen_is_thirteen: !expr is_thirteen(13)
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['five_plus_seven'], 12)
    self.assertEqual(y['shape_with_4_sides'], 'quadrilateral')
    self.assertEqual(y['seven_is_thirteen'], 'no')
    self.assertEqual(y['thirteen_is_thirteen'], 'YES!!!')

  def test_func_example_from_the_readme(self):
    YamletOptions = self.Opts
    loader = yamlet.Loader(YamletOptions(functions={
        'quadratic': lambda a, b, c: (-b + (b * b - 4 * a * c)**.5) / (2 * a)
    }))
    data = loader.load('''
        a: 2
        b: !expr a + c  # Evaluates to 9, eventually
        c: 7
        quad: !expr quadratic(a, b, c)
        ''')
    self.assertEqual(data['quad'], -1)
    self.assertEqual(data['a'], 2)
    self.assertEqual(data['b'], 9)
    self.assertEqual(data['c'], 7)

  def test_dynamic_key_example_from_the_readme(self):
    YAMLET = '''# Yamlet
    static_key: dynamic
    tup: !expr |
      { '{static_key}_key': 'value' }
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['tup'].keys(), {'dynamic_key'})

  def test_nullification_example_from_the_readme(self):
    YAMLET = '''# Yamlet
    t1:
      key_to_keep: present
      key_to_delete: also present
    deleter:
      key_to_delete: !null
    t2: !expr t1 deleter
    t3: !expr t1 t2
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['t1'].keys(), {'key_to_keep', 'key_to_delete'})
    self.assertEqual(y['t2'].keys(), {'key_to_keep'})
    self.assertEqual(y['t3'].keys(), {'key_to_keep', 'key_to_delete'})
    self.assertEqual(len(y['t1']), 2)
    self.assertEqual(len(y['t2']), 1)
    self.assertEqual(len(y['deleter']), 1)
    self.assertEqual(len(y['t3']), 2)

  def test_most_basic_goddamn_example_from_the_readme(self):
    loader = yamlet.Loader()
    t = loader.load_file('yaml-gcl.yaml')
    self.assertEqual(t['childtuple']['coolbeans'],
                     'Hello, world! I say cooool beans!')
    self.assertEqual(t['childtuple2']['coolbeans'],
                     'Hello, world! I say awesome sauce!')

  def test_easy_load(self):
    hi = yamlet.load('hi')
    self.assertEqual(hi, 'hi')

  def test_easy_load_file(self):
    t = yamlet.load_file('yaml-gcl.yaml')
    self.assertEqual(t['childtuple']['coolbeans'],
                     'Hello, world! I say cooool beans!')
    self.assertEqual(t['childtuple2']['coolbeans'],
                     'Hello, world! I say awesome sauce!')

  def test_one_fish_two_fish_from_readme(self):
    YAMLET = '''# Yamlet
    my_array: [1, 2, 'red', 'blue']
    fishes: !expr r', '.join('{x} fish' for x in my_array)
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertEqual(t['fishes'], '1 fish, 2 fish, red fish, blue fish')

  def test_locals_example_from_readme(self):
    yamlet_config = '''# Yamlet
    !local var_that_will_not_show_up: Hello, world!
    !local var_that_would_error: !expr undefined varnames with bad syntax
    var_that_will_show_up: !expr var_that_will_not_show_up
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(yamlet_config)
    self.assertEqual(t.evaluate_fully(),
                     {'var_that_will_show_up': 'Hello, world!'})
    # Repeat the above experiment using the exact wording from the readme
    t = yamlet.load(yamlet_config)
    self.assertEqual(t.evaluate_fully(),
                     {'var_that_will_show_up': 'Hello, world!'})

  def test_locals_example_from_readme_second(self):
    yamlet_config = '''# Yamlet
    tup1:
      !local my_local: irrelevant
      my_nonlocal: !fmt 'Hello, {my_local}!'
    tup2: !composite
      - tup1
      - my_local: world
    '''
    loader = yamlet.Loader(self.Opts())
    parsed_config = loader.load(yamlet_config)
    self.assertEqual(parsed_config['tup2'].evaluate_fully(),
                     {'my_nonlocal': 'Hello, world!'})


@ParameterizedOnOpts
class FieldTests(unittest.TestCase):
  def test_icu_library_description(self):
    YAMLET = '''# Yamlet
    !local LIB_PREFIX: 'lib'
    !local STATIC_LIB_EXT: 'a'
    !local SHARED_LIB_EXT: 'so'
    icu_lib_template: !template
      !local STATIC_LIB_PREFIX: !expr ('s' if 'linux' == 'windows' else '')
      static_libs: !expr |
          ['{LIB_PREFIX}{STATIC_LIB_PREFIX}{name}.{STATIC_LIB_EXT}' for name in lib_names]
      dynamic_libs: !expr |
          ['{LIB_PREFIX}{name}.{SHARED_LIB_EXT}' for name in lib_names]
      !local lib_names: !external

    module_libs:
      icu:
        version: 50.2.0.R
        provides:
          icu-i18n: !expr |
              icu_lib_template { lib_names: ['icuin', 'icuuc', 'icudt'] }
          icu-io: !composite
            - icu_lib_template
            - lib_names: ['icuio', 'icuin', 'icuuc', 'icudt']
          icu-le: !composite
            - icu_lib_template
            - lib_names:
              - icule
              - icuuc
              - icudt
          icu-lx: !composite
            - icu_lib_template
            - lib_names: ['iculx', 'icule', 'icuuc', 'icudt']
          icu-uc: !composite
            - icu_lib_template
            - lib_names: ['icule', 'icuuc', 'icudt']
    '''
    loader = yamlet.Loader(self.Opts())
    t = loader.load(YAMLET)
    self.assertDictEqual(t.evaluate_fully(), {
      'module_libs': {
        'icu': {
          'version': '50.2.0.R',
          'provides': {
            'icu-i18n': {
              'static_libs': ['libicuin.a', 'libicuuc.a', 'libicudt.a'],
              'dynamic_libs': ['libicuin.so', 'libicuuc.so', 'libicudt.so'],
            },
            'icu-io': {
              'static_libs': ['libicuio.a', 'libicuin.a', 'libicuuc.a', 'libicudt.a'],
              'dynamic_libs': ['libicuio.so', 'libicuin.so', 'libicuuc.so', 'libicudt.so'],
            }, 'icu-le': {
              'static_libs': ['libicule.a', 'libicuuc.a', 'libicudt.a'],
              'dynamic_libs': ['libicule.so', 'libicuuc.so', 'libicudt.so'],
            }, 'icu-lx': {
              'static_libs': ['libiculx.a', 'libicule.a', 'libicuuc.a', 'libicudt.a'],
              'dynamic_libs': ['libiculx.so', 'libicule.so', 'libicuuc.so', 'libicudt.so'],
            },
            'icu-uc': {
              'static_libs': ['libicule.a', 'libicuuc.a', 'libicudt.a'],
              'dynamic_libs': ['libicule.so', 'libicuuc.so', 'libicudt.so'],
            }
          }
        }
      }
    })



@ParameterizedOnOpts
class TestCustomConstructors(unittest.TestCase):
  '''
  XXX: Ruamel's constructor object is static and inherited between all YAML()
  instances, so this class tries to use a unique name for each test's tags
  to avoid cross-contamination.
  '''
  class CustomType_LN:
    def __init__(self, loader, node): self.value = loader.construct_scalar(node)
    def __str__(self): return self.value
    def __repr__(self): return f'CustomType_LN({self.value})'
    def __eq__(self, other):
      return (isinstance(other, TestCustomConstructors.CustomType_LN)
              and other.value == self.value)

  class CustomType_V:
    def __init__(self, value): self.value = value
    def __str__(self): return self.value
    def __repr__(self): return f'CustomType_V({self.value})'
    def __eq__(self, other):
      return (isinstance(other, TestCustomConstructors.CustomType_V)
              and other.value == self.value)

  def test_composited_tags(self):
    YAMLET = '''# Yamlet
    one: 1
    two: 2
    case1: !custom1 one + two
    case2: !custom1:fmt '{one} + {two}'
    case3: !custom1:expr one + two
    '''
    loader = yamlet.Loader(self.Opts())
    loader.add_constructor('!custom1', self.CustomType_V,
                           style=yamlet.ConstructStyle.SCALAR)
    t = loader.load(YAMLET)
    self.assertIsInstance(t['case1'], self.CustomType_V)
    self.assertIsInstance(t['case2'], self.CustomType_V)
    self.assertIsInstance(t['case3'], self.CustomType_V)
    self.assertEqual(t['case1'].value, 'one + two')
    self.assertEqual(t['case2'].value, '1 + 2')
    self.assertEqual(t['case3'].value, 3)

  def test_raw_tag(self):
    YAMLET = '''# Yamlet
    one: 1
    two: 2
    case1: !custom2 one + two
    '''
    loader = yamlet.Loader(self.Opts())
    loader.add_constructor('!custom2', self.CustomType_LN)
    t = loader.load(YAMLET)
    self.assertIsInstance(t['case1'], self.CustomType_LN)
    self.assertEqual(t['case1'].value, 'one + two')

  def test_expr_style_tag(self):
    YAMLET = '''# Yamlet
    one: 1
    two: 2
    case1: !custom3 one + two
    case2: !custom3:raw one + two
    case3: !custom3:fmt '{one} + {two}'
    case4: !custom3:expr one + two
    '''
    loader = yamlet.Loader(self.Opts())
    loader.add_constructor('!custom3', self.CustomType_V,
                           style=yamlet.ConstructStyle.EXPR)
    t = loader.load(YAMLET)
    self.assertIsInstance(t['case1'], self.CustomType_V)
    self.assertIsInstance(t['case2'], self.CustomType_V)
    self.assertIsInstance(t['case3'], self.CustomType_V)
    self.assertIsInstance(t['case4'], self.CustomType_V)
    self.assertEqual(t['case1'].value, 3)
    self.assertEqual(t['case2'].value, 'one + two')
    self.assertEqual(t['case3'].value, '1 + 2')
    self.assertEqual(t['case4'].value, 3)

  def test_fmt_style_tag(self):
    YAMLET = '''# Yamlet
    one: 1
    two: 2
    case1: !custom4 '{one} + {two}'
    case2: !custom4:raw one + two
    case3: !custom4:fmt '{one} + {two}'
    case4: !custom4:expr one + two
    '''
    loader = yamlet.Loader(self.Opts())
    loader.add_constructor('!custom4', self.CustomType_V,
                           style=yamlet.ConstructStyle.FMT)
    t = loader.load(YAMLET)
    self.assertIsInstance(t['case1'], self.CustomType_V)
    self.assertIsInstance(t['case2'], self.CustomType_V)
    self.assertIsInstance(t['case3'], self.CustomType_V)
    self.assertIsInstance(t['case4'], self.CustomType_V)
    self.assertEqual(t['case1'].value, '1 + 2')
    self.assertEqual(t['case2'].value, 'one + two')
    self.assertEqual(t['case3'].value, '1 + 2')
    self.assertEqual(t['case4'].value, 3)

  def test_fancy_ctor_in_opts(self):
    YAMLET = '''# Yamlet
    one: 1
    two: 2
    case1: !custom5 '{one} + {two}'
    case2: !custom5:raw one + two
    case3: !custom5:fmt '{one} + {two}'
    case4: !custom5:expr one + two
    '''
    loader = yamlet.Loader(self.Opts(constructors={
        '!custom5': {'ctor': self.CustomType_V,
                     'style': yamlet.ConstructStyle.FMT}}))
    t = loader.load(YAMLET)
    self.assertIsInstance(t['case1'], self.CustomType_V)
    self.assertIsInstance(t['case2'], self.CustomType_V)
    self.assertIsInstance(t['case3'], self.CustomType_V)
    self.assertIsInstance(t['case4'], self.CustomType_V)
    self.assertEqual(t['case1'].value, '1 + 2')
    self.assertEqual(t['case2'].value, 'one + two')
    self.assertEqual(t['case3'].value, '1 + 2')
    self.assertEqual(t['case4'].value, 3)


if __name__ == '__main__':
  unittest.main()
