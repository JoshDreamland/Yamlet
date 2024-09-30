# Yamlet: A GCL-like templating engine for YAML

Yamlet is a tool for writing complex configurations in YAML.

YAML itself doesn't support operations such as string concatenation,
so a common wishlist item for people is the ability to use a YAML anchor
to extend one tuple value inside another.

E.g.
```yaml
key1: &anchor my common value
key2: *anchor extra specialized value  # THIS DOES NOT WORK IN YAML!
```

GCL, Google's Generic Configuration Language, solves this problem more
generally by deferring variable lookups into each scope that includes
them. Yamlet is a Pythonic implementation of this idea, in the way that
JSonnet is a... jsonish implementation. The key difference is that JSonnet
is owned by Google while Yamlet is hacked together by a former Google
employee in a few hundred lines of Python. On the plus side, tuple
composition seems to actually work in this engine, which is more than
I can say for `gcl.py` from the Pip repo.

This tool is lightweight at the moment and kind of fun to reason about,
so drop me issues or feature requests and I'll try to attend to them.

The biggest change that would make this project nicer is if YAML supported
raw strings (literal style) for specific constructors without the use of a
particular style token. In particular, it's annoying having to insert a
pipe and newline before any expression that you'd like to be evaluated
GCL-style instead of YAML style.

To work around this a bit, I've added `!fmt` and `!composite` tags on top of
the core `!expr` tag so that the YAML parser can handle the string interpreting
and nested tuple parsing. So in the below examples, I could have used
`coolbeans: !fmt 'Hello, {subject}! I say {cool} {beans}!'` instead of that
pipe nonsense if I didn't want to show off string concatenation explicitly.

## Examples
Consider a main file, `yaml-gcl.yaml`:
```yaml
t1: !import yaml-gcl2.yaml
t2:
  beans: beans
  coolbeans: !expr |
      'Hello, {subject}! ' + 'I say {cool} {beans}!'

childtuple: !expr t1.tuple t2
childtuple2: !expr t2 t1.tuple2
```

Then a separate file, `yaml-gcl2.yaml`:
```yaml
tuple:
  cool: cooool
  beans: sauce
  subject: world
tuple2: !composite
  - tuple
  - {
    cool: awesome
  }
```

Reading these files in Python:
```python
import yamlet

loader = yamlet.DynamicScopeLoader()
t = loader.load('yaml-gcl.yaml')
print(t['childtuple']['coolbeans'])
print(t['childtuple2']['coolbeans'])
```

Will print the following:
```
Hello, world! I say cooool beans!
Hello, world! I say awesome sauce!
```

Flipping the definitions of `childtuple` and `childtuple2` to instead read
`t2 t1.tuple` and `t1.tuple2 t2` would instead print, respectively,
`cooool sauce` and `awesome beans`, which would be upsetting, so don't do that.
I mean, that's by design; this is how GCL templating works. Each tuple you
chain onto the list overwrites the values in the previous tuples, and then
expressions inherited from those tuples will use the new values.


## Strengths
Because this is baked on top of YAML in Python, we have pretty good power and
modularity. I didn't do any weird hacks to implement this; it's just YAML with
a few custom constructors to handle deferred expression evaluation.

## Errata
Many? Like, I do very little type checking, and syntax errors look pretty ugly.
Just wanted to get a draft out there. Gonna try to use this for my own purposes
and will push any fixes here.

A few I can think of:
- No conditionals.
- No helper functions right now (e.g. time functions, formatting functions).
- Can't currently declare more tuples with {} in a raw expression.
- No lambdas.
- Passing junk to these constructors will vomit inscrutible errors.
