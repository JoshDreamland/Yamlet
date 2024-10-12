# Yamlet: A GCL-like templating engine for YAML

Yamlet is a tool for writing complex configurations in YAML.

It is reminiscent of GCL, but has strict YAML syntax, while offering complex
expression evaluation and templating operations that would have otherwised
required an engine such as Jinja.

YAML itself doesn't support even simple operations such as string concatenation,
so a common wishlist item for people is the ability to use a YAML anchor to
extend one tuple value inside another.

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
GCL-style instead of YAML style. Similarly, it would be nice if I could
define an `!else:` constructor that starts a mapping block. Until then,
the best workaround I can recommend is habitually parenthesizing every Yamlet
expression, and putting spaces after all your tokens like it's the 80s.

To help work around this, I've added `!fmt` and `!composite` tags on top of
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

Additionally, you can use tuple composition to simply string together
conditionals:

```yaml
t: !composite
  - !if (1 + 1 == 2):
    a: 10
    b: { ba: 11 }
  - !else
    crap: value
  - !if ('shark' == 'fish'):
    more-crap: values
  - !else
    b: { bb: 12 }
    c: 13
  - !if ('crab' == 'crab'):
    d: 14
  - !else
    crapagain: 2
```

Note that specifically because of the aforementioned problems, you must use this
list flow in conditional statements (with ` - `), or else be extremely careful
to put a space between your `!else` tag and the following colon.

## Features
The following are implemented:
- String formatting (as above)
- GCL-Like tuple composition
- Conditionals for composition flows
- File import (to allow splitting up configs or splitting out templates)
- Lambda expressions
- Custom functions (defined in Python)
- Explicit composition using `up`/`super`
  - `up` refers to the scope that contains the current scope, as in nested
     tuples.
  - `super` refers to the scope from which the current scope was composed,
     as in the template from which some of its values were inherited.

## Strengths
Because this is baked on top of YAML in Python, we have pretty good power and
modularity. I didn't do any weird hacks to implement this; it's just YAML with
a few custom constructors to handle deferred expression evaluation.

## Caveats
### Yamlet is an extension of YAML
Yamlet is built on top of YAML. That means that the first tool to parse your
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

### Map literals in Yamlet expressions
Yamlet maps are meant to look like YAML maps, but they aren't exactly the same:

```yaml
my_yamlet_map: !expr |
  {
    key: 'my string value with {inlined} {expressions}',
    otherkey: 'my other value'
  }
```

This is because the Python parser is used to handle expressions in Yamlet,
including interpreting mapping flows (which are based instead on Python dicts).
I have taken the liberty of allowing raw names as the key (per YAML) without
unpacking these as expressions (per Python). To use a variable as the key, you
can say `'{key_variable}': value_variable`, but note that the `key_variable`
must be available in the compositing scope (the scope containing the mapping
expression) and CANNOT be deferred to access values from the resulting tuple.
The values within a Yamlet mapping, however, *are* deferred.

So the real weirdness here is that this isn't a Python dict literal, because
name variables are not variables, and this isn't a YAML mapping literal, because
every value is a raw Yamlet expression, wherein strings must be quoted.
An additional difference from YAML mapping flows is that all keys must have
values; you may not simply mix dict pairs and set keys (YAML allows this,
Python and Yamlet do not).

## Differences from GCL
### Missing features
A few currently missing features I can think of:
- No assertions.
- Support for `external` and `null` in expressions.
  - `external` evaluates to `external` when used in any operation. Requesting
     an external value from a tuple explicitly results in an error. This is the
     default for any undeclared value, so I haven't seen the need.
  - `null` erases a key from a tuple, omitting it in compositing operations
     unless it is added afterward in a further tuple.
- More builtin functions (`substr`, `tail`, ...).
- Support for the `args` tuple.
- Support for `final` and `local` expressions. The language might be better
  without these...

### Improvements over GCL
Yamlet tracks all origin information, so there's no need for a separate utility
to tell you where an expression came from. Consequently, you may chain `super`
expressions within Yamlet and it will "just work." You can also invoke
`explain_value` in any resulting dictionary to retrieve a description of how the
value was determined. This feature could use more testing and debugging for
beautification purposes.

## Differences from the rest of industry
Yamlet is probably the only templating or expression evaluation engine that
doesn't use jq. If you want to use jq, you can create a function that accepts
a jq string and use Yamlet's literal formatting to put values in the string.

Yamlet shares a more procedural syntax with GCL. It's currently missing
arithmetic operations because I didn't see anyone needing them, but they're
a seven-line patch.

A Yamlet configuration file (or "program," as GCL calls its own scripts) doesn't
really need jq, because you can just invoke routines in it functionally.

It's also worth pointing out that Jinja does not pair well with YAML because
Jinja lends itself to cutting and pasting lines of file, and YAML uses indent
as a form of syntax. Import statements in Yamlet import the final tuple value,
not a chunk of unprocessed file.

## What's in a name?
Who knows! Maybe it plays on "JSonnet" by building a sort of Shakespearean motif
around the name "Hamlet." Maybe it's a Portmanteau of "YAML" and "Borglet," or,
perhaps more obviously, some amalgam of "YAML" and "template."
Maybe it plays more directly on "applet" and how one might write them in YAML.
Maybe it's simply the product of whatever sort of fever dream leads to the
inception of a tool such as this.
