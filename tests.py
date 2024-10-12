import traceback
import unittest
import yamlet

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
    for comp in ['comp1', 'comp2', 'comp3']:
      self.assertTrue(comp in y)
      comp = y[comp]
      for k1, v1 in {'a': 100, 'b': 200, 'c': 300}.items():
        self.assertTrue(k1 in comp)
        comp1 = comp[k1]
        for k2, v2 in {'a': 10, 'b': 20, 'c': 30}.items():
          self.assertTrue((k1 + k2) in comp1, f'{k1 + k2} in {comp1}')
          comp2 = comp1[k1 + k2]
          for k3, v3 in {'a': 1, 'b': 2, 'c': 3}.items():
            self.assertTrue((k1 + k2 + k3) in comp2, f'{k1 + k2 + k3} in {comp2}')
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
    t3: !expr |
        t0 { animal: 'fish' }
    t4: !expr |
        t0 { animal: 'squirrel' }
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    print(y['t1'])
    self.assertEqual(y['t1']['environment'], 'water')
    self.assertEqual(y['t2']['attention'], 'pats')
    self.assertEqual(y['t2']['toys'], ['squeaky ball'])
    self.assertEqual(y['t3']['diet'], 'meat')
    self.assertEqual(y['t4']['recommendation'], 'specialist')
    self.assertEqual(len(y['t1']), 1)
    self.assertEqual(len(y['t2']), 2)
    self.assertEqual(len(y['t3']), 1)
    self.assertEqual(len(y['t4']), 1)

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
    !if ('crab' == 'crab'):
      d: 14
    !else :
      crapagain: 2
    '''
    print('Beginning weird test')
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    print(type(y), ':')
    print(y)
    self.assertTrue('a' in y)
    self.assertTrue('b' in y)
    self.assertTrue('c' in y)
    self.assertTrue('d' in y)
    self.assertEqual(y['a'], 10)
    self.assertEqual(y['b']['ba'], 11)
    self.assertEqual(y['b']['bb'], 12)
    self.assertEqual(y['c'], 13)
    self.assertEqual(y['d'], 14)
    self.assertFalse('crap' in y)
    self.assertFalse('more-crap' in y)
    self.assertFalse('crapagain' in y)


class TestRecursion(unittest.TestCase):
  def test_recursion(self):
    YAMLET = '''# Yamlet
    recursive:
      a: !expr b
      b: !expr a
    '''
    loader = yamlet.DynamicScopeLoader()
    y = loader.loads(YAMLET)
    ex, val = None, None
    try:
      val = y['recursive']['a']
    except RecursionError as exc:
      ex = ''.join(traceback.format_exception(exc))
      tb = traceback.format_tb(exc.__traceback__)
    self.assertTrue(ex is not None, f'Did not throw an exception; got {val}')
    ex_lines = ex.splitlines()
    fex = '  > ' + '\n  > '.join('\n'.join(ex_lines).splitlines())
    self.assertLess(len(tb), 3, f'Stack trace is ugly:\n{fex}')
    self.assertGreater(len(ex_lines), 15, f'Yamlet trace is too small:\n{fex}')
    self.assertLess(len(ex_lines), 30, f'Yamlet trace is too large:\n{fex}')


if __name__ == '__main__':
  unittest.main()
