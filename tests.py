import traceback
import unittest
import yamlet

from contextlib import contextmanager

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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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
            self.assertTrue((k1 + k2 + k3) in comp2, f'{k1 + k2 + k3} in {compn}: {comp2}')
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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    self.assertEqual(y['t2']['sub']['deferred'], 'Hello, world!')

  def test_parents_update_3(self):
    YAMLET = '''# YAMLET
    t1:
      deferred: !fmt Hello, {val}!
    t2:
      val: world
      sub: !expr t1
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    self.assertEqual(y['t2']['sub']['deferred'], 'Hello, world!')

  def test_parents_update_4(self):
    YAMLET = '''# YAMLET
    t1:
      deferred: !fmt Hello, {val}!
    t2:
      val: world
      sub: !composite
        - t1
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    self.assertEqual(y['t2']['sub']['deferred'], 'Hello, world!')

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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    with AssertRaisesCleanException(ValueError):
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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    self.assertEqual( y['t1']['sub']['exp'], 'value')


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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    self.assertEqual(y['t2']['sub']['counting'], 'one two three four')


class TestStringMechanics(unittest.TestCase):
  def test_escaped_braces(self):
    YAMLET = '''# Yamlet
    v: Hello
    v2: world
    v3: !fmt '{{{v}}}, {{{{{v2}}}}}{{s}}!'
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    self.assertEqual(y['v3'], '{Hello}, {{world}}{s}!')


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

    opts = yamlet.YamletOptions(functions={'func': func})
    loader = yamlet.DynamicScopeLoader(opts)
    y = loader.loads(YAMLET)
    self.assertTrue(y['t']['v'] is uniq)
    self.assertEqual(side_effect, ['Hello, ', ['world!']])


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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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
      !else :
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
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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

  def test_if_statements(self):
    YAMLET = '''# Yamlet
    !if (1 + 1 == 2):
      a: 10
      b: { ba: 11 }
    !else :
      crap: value
    !if ('shark' == 'fish'):
      more-crap: values
    !elif ('crab' == 'crab'):
      b: { bb: 12 }
      c: 13
    !else :
      still-crap: 10
    !if ('fish' == 'fish'):
      d: 14
    !else :
      crapagain: 2
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
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
      !else :
        crap: value
      !if (2 + 2 == 6):
        crap: value
      !else :
        b: { bb: 12 }
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    self.assertTrue('a' in y['t'])
    self.assertTrue('b' in y['t'])
    self.assertEqual(y['t']['a'], 10)
    self.assertEqual(y['t']['b']['ba'], 11)
    self.assertEqual(y['t']['b']['bb'], 12)
    self.assertEqual(y['t'].keys(), {'a', 'b'})
    self.assertFalse('crap' in y['t'])

class AssertRaisesCleanException:
  def __init__(self, exc_tp, min_context=15, max_context=30):
    self.exc_tp = exc_tp
    self.ex = None
    self.val = None
    self.min_context = min_context
    self.max_context = max_context

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    if exc_type is None:  # No exception was raised
      raise AssertionError('Did not throw an exception.')

    if not issubclass(exc_type, self.exc_tp):
      # Let other exceptions pass through
      return False

    # Handle the expected exception
    ex = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    tb = traceback.format_tb(exc_traceback)

    exlines = ex.splitlines()
    fex = '  > ' + '\n  > '.join('\n'.join(exlines).splitlines())
    if len(tb) >= 3:
      raise AssertionError(f'Stack trace is ugly:\n{fex}')
    if len(exlines) <= self.min_context:
      raise AssertionError(f'Yamlet trace is too small:\n{fex}\n'
                           f'The above exception should have been at least '
                           f'{self.min_context} lines, but was {len(exlines)}.')
    if len(exlines) >= self.max_context:
      raise AssertionError(f'Yamlet trace is too large:\n{fex}\n'
                           f'The above exception should have been at most '
                           f'{self.max_context} lines, but was {len(exlines)}.')

    # Suppress the exception (so it won't propagate)
    return True

class TestRecursion(unittest.TestCase):
  def test_recursion(self):
    YAMLET = '''# Yamlet
    recursive:
      a: !expr b
      b: !expr a
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    with AssertRaisesCleanException(RecursionError):
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
    child: !composite
      - parent
      - childvalue: !expr parentvalue != 'blue'
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    with AssertRaisesCleanException(RecursionError, max_context=40):
      val = y['child']['parentvalue']
      self.fail(f'Did not throw an exception; got `{val}`')


if __name__ == '__main__':
  unittest.main()
