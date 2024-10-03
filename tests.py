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
      tb = traceback.format_tb(exc.__traceback__)
      ex = str(exc)
    self.assertTrue(ex is not None, f'Did not throw an exception; got {val}')
    fmt_tb = '  >' + '\n  >'.join('\n'.join(tb).splitlines())
    self.assertLess(len(tb), 3, f'Stack trace is ugly:\n{fmt_tb}')
    ex_lines = ex.splitlines()
    self.assertGreater(len(ex_lines), 15, f'Yamlet trace is too small:\n{ex}')
    self.assertLess(len(ex_lines), 30, f'Yamlet trace is too large:\n{ex}')


if __name__ == '__main__':
  unittest.main()
