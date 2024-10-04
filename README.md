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


## Features
The following are implemented:
- GCL-Like tuple composition
- Custom functions
- Lambda expressions

## Strengths
Because this is baked on top of YAML in Python, we have pretty good power and
modularity. I didn't do any weird hacks to implement this; it's just YAML with
a few custom constructors to handle deferred expression evaluation.

## Caveats
### YAML as the carrier
Yamlet is build on top of YAML. That means that the first tool to parse your
configuration file ***is** a YAML interpreter*, namely Ruamel. The facilities
offered by this tool will only work for you if you can convey your expression
strings through Ruamel. As stated above, this tool has a separate tag for `!fmt`
(formatting string values) and `!expr`. This is because if you try to say
`my_string: !expr 'my formatted string with {inlined} {expressions}'`, you are
NOT going to get a string! Ruamel will interpret that string value, removing
the single quotes and handing Yamlet a bunch of drivel. I work around that by
adding `!fmt`, which treats the entire Ruamel value as a string literal.
An alternative is to do this:
```python
my_string: !expr |
  'my formatted string with {inlined} {expressions}'
```

This is, at the time of this writing, the only way to trigger literal style for
a YAML value. I cannot accomplish it from a tag.

### Maps in Yamlet
Yamlet maps are meant to look like YAML maps, but they aren't:

```yaml
my_yamlet_map: !expr |
  {
    key: 'my string value with {inlined} {expressions}',
    otherkey: 'my other value'
  }
```

This is because the Python parser is used to handle expressions in Yamlet.
I have taken the liberty of allowing raw names as the key without unpacking
these as expressions, per Python. To use a variable as the key, you can say
`'{key_variable}': value_variable`, but note that the `key_variable` must be
available in the compositing scope (the scope containing the mapping expression)
and CANNOT be deferred to access values from the resulting tuple. The values
within a Yamlet mapping, however, *are* deferred.

So the real weirdness here is that this isn't a Python dict literal, because
name variables are not variables, and this isn't a YAML mapping literal, because
every value is a raw Yamlet expression, *followed by a comma.* Unlike YAML, the
commas are not optional, here. In fact, I'll bet the behavior is really weird
right now if you forget one and I don't know what I'll do to fix that.

## Errata
Mostly featureful, now, but some missing features I'll enumerate here and some
janky or interesting behavior above in "Caveats."

A few missing features I can think of:
- No assertions.
- Support for "external" and "null" in expressions
  - "external" evaluates to external in any operation.
  - "null" erases a key from a tuple, omitting it in compositing operations
    unless it is added afterward.
- More builtin functions (`substr`, `tail`, ...)
- Support for the `args` tuple

## What's in a name?
Who knows! Maybe it plays on "JSonnet" by building a sort of Shakespearean motif
around the name "Hamlet." Maybe it's a Portmanteau of "YAML" and "Borglet," or,
perhaps more obviously, some amalgam of "YAML" and "template."
Maybe it plays more directly on "applet" and how one might write them in YAML.
Maybe it's simply the product of whatever sort of fever dream leads to the
inception of a tool such as this.
