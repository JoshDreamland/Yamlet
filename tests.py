import os
import traceback
import unittest
import yamlet

from contextlib import contextmanager

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
  DebugAllClass = mkclass(f'{klass.__name__}_DebugAll',
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
            t2_only_key2: 'Second value that only appears in t1'
          }][0],
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
class TestStringMechanics(unittest.TestCase):
  def test_escaped_braces(self):
    YAMLET = '''# Yamlet
    v: Hello
    v2: world
    v3: !fmt '{{{v}}}, {{{{{v2}}}}}{{s}}!'
    '''
    loader = yamlet.Loader(self.Opts())
    y = loader.load(YAMLET)
    self.assertEqual(y['v3'], '{Hello}, {{world}}{s}!')


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

  def test_cond_routine(self):
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
    tp:
      !if first == 'A':
        !if middle == 'X':
          !if last == 1:
            result: AX1
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
  class RelativeStringValue(yamlet.Compositable):
    def __init__(self, loader_or_str, node_if_loader=None):
      if node_if_loader:
        self.val = str(loader_or_str.construct_scalar(node_if_loader))
      else:
        self.val = loader_or_str

    def yamlet_merge(self, other, ectx):
      if isinstance(other, str): self.val = f'{self.val} {other}'.strip()
      elif isinstance(other, TestFlatCompositing.RelativeStringValue):
        self.val = f'{self.val} {other.val}'.strip()
      else: ectx.Raise(
          f'Cannot composite {type(other).__name__} with RelativeStringValue')

    def yamlet_clone(self, other):
      return TestFlatCompositing.RelativeStringValue(self.val)

    def __eq__(self, other):
      if isinstance(other, str): return self.val == other
      return self.val == other.val

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

  def test_specializing_conditions(self):
    YAMLET = '''# Yamlet
    tp:
      variable: !rel defaulted value
      switch: off
      !if switch == 'on':
        variable: !rel specialized value
    boring: !expr tp
    flashy: !expr tp {switch:'on'}
    '''
    ctors = {'!rel': TestFlatCompositing.RelativeStringValue}
    loader = yamlet.Loader(self.Opts(constructors=ctors))
    y = loader.load(YAMLET)
    self.assertEqual(y['tp']['variable'], 'defaulted value')
    self.assertEqual(y['flashy']['variable'], 'defaulted value specialized value')
    self.assertEqual(y['boring']['variable'], 'defaulted value')


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
    self.assertEqual(y['t2']['sub']['subsub']['test'], 'base level1 level2 override')

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


if __name__ == '__main__':
  unittest.main()
