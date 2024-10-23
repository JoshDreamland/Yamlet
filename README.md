# Yamlet: A GCL-like templating engine for YAML

Yamlet is a tool for writing complex configurations in YAML.

It is reminiscent of GCL, but it adheres to strict YAML syntax, while offering
complex expression evaluation and templating operations that would otherwise
require an engine such as Jinja.

YAML itself doesn't support even simple operations such as string concatenation,
so a common wishlist item for people is the ability to use a YAML anchor to
extend one value inside another.

For example:
```yaml
key1: &anchor my common value
key2: *anchor extra specialized value  # THIS DOES NOT WORK IN YAML!
```

Yamlet solves this explicitly, on top of bundling a comprehensive templating
engine:

```yaml
key1: my common value
key2: !expr key1 + ' my extra specialized value'
```

GCL, Google's Generic Configuration Language, solves this problem more
generally by deferring variable lookups into each scope that includes
them. Yamlet is a Pythonic implementation of this idea, in the way that
JSonnet is a... jsonish implementation. The key difference is that JSonnet
is owned by Google while Yamlet is hacked together by a former Google
employee in a few hundred lines of Python. On the plus side, tuple
composition seems to actually work in this engine, which is more than
I can say for `gcl.py` on Pip.

(*Note for the uninitiated to GCL: A "Tuple" is the equivalent of a dictionary.*)

This tool is lightweight at the moment and kind of fun to reason about,
so drop me issues or feature requests and I'll try to attend to them.

The biggest change that would make this project nicer is if YAML supported
raw strings (literal style) for specific constructors without the use of a
specific style token. In particular, it's annoying having to insert a pipe
and newline before any expression that you'd like to be evaluated GCL-style
instead of YAML style. Similarly, it would be great if I could define an
`!else:` constructor that starts a mapping block, or revise the spec to
disallow colons at the end of tags (where followed by whitespace). Until then,
the best workaround I can recommend is to habitually parenthesize every Yamlet
expression and put spaces after all your tokens like it's the 80s.

To help work around this, I've added `!fmt` and `!composite` tags on top of
the core `!expr` tag so that the YAML parser can handle string interpretation
and nested tuple parsing. In the examples below, I could have used
`coolbeans: !fmt 'Hello, {subject}! I say {cool} {beans}!'` instead of that
pipe nonsense if I didn't want to show off string concatenation explicitly.
I could probably have also gotten away with parentheses.

I've also added a stream preprocessor that replaces `!else:` with `!else :`
for when someone inevitably forgets or doesn't read this.


## Installation

Yamlet is not currently available on Pip. It is a single Python file; you may
copy it into your project wherever you like.

I will attempt to publish to PyPI sooner or later.


## Features

Here’s a summary of Yamlet’s features:
- [String formatting](#string-formatting)
- [GCL-Like tuple composition](#tuple-composition)
- [Conditionals, as seen in procedural languages](#conditionals)
- [File Imports](#file-imports)
  (to allow splitting up configs or splitting out templates)
- [Lambda expressions](#lambda-expressions)
- [Custom functions](#custom-functions) (defined in Python)
- [GCL Special Values](#gcl-special-values) `null` and `external`.
- Explicit [value referencing](#scoping-quirks) in composited tuples using
  `up`/`super`
  - `up` refers to the scope that contains the current scope, as in nested
     tuples.
  - `super` refers to the scope from which the current scope was composed,
     as in the template from which some of its values were inherited.


## Examples

Here’s a whirlwind tour of Yamlet. Consider a main file, `yaml-gcl.yaml`:

```yaml
t1: !import yaml-gcl2.yaml
t2:
  beans: beans
  coolbeans: !expr |
      'Hello, {subject}! ' + 'I say {cool} {beans}!'

childtuple: !expr t1.tuple t2
childtuple2: !expr t2 t1.tuple2
```

And a separate file, `yaml-gcl2.yaml`:

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

In Python, you can read these files like this:

```python
import yamlet

loader = yamlet.Loader()
t = loader.load_file('yaml-gcl.yaml')
print(t['childtuple']['coolbeans'])
print(t['childtuple2']['coolbeans'])
```

This will print the following:

```
Hello, world! I say cooool beans!
Hello, world! I say awesome sauce!
```

You can try this out by running `example.py`.

Flipping the definitions of `childtuple` and `childtuple2` to instead read
`t2 t1.tuple` and `t1.tuple2 t2` would instead print `cooool sauce` and
`awesome beans`, respectively—which would be upsetting, so don't do that.
(It's by design; this is how GCL templating works.) Each tuple you chain onto
the list overwrites the values in the previous tuples, and then expressions
inherited from those tuples will use the new values.

Placing tuples next to each other in Yamlet composites them. For example, you
can use `my_template { my_key: overridden value }` to *instantiate* the tuple
`my_template` and override `my_key` within that tuple with a new value.

I'll break this down better later in this document
(see [Tuple Composition](#tuple-composition)).

### Conditionals

Yamlet adds support for conditional statements, on top of `cond()` as used in
the Google GCL spec. In Yamlet, conditionals look like this:

```yaml
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
```

Note that YAML requires you to have a space between the `!else` tag and the
following colon. However, Yamlet's stream preprocessor handles this for you,
at the cost of any data that would otherwise contain the string `"!else:"`...
which should be a non-issue, right?

### String Formatting

Yamlet offers several syntaxes for string composition.

```yaml
subject: world
str1: !expr ('Hello, {subject}!')
str2: !expr ('Hello, ' + subject + '!')
str3: !fmt 'Hello, {subject}!'
```

All of these will evaluate to `Hello, world!`.

The next section explains how to create a template that lets you modify the
value of `subject` from within your program or other contexts in Yamlet.

### Tuple Composition

In GCL, the basic unit of configuration is a tuple, and templating happens
through extension. Yamlet inherits this behavior. Tuple composition can be
tricky to understand, so I’ll push the system to its limits to paint a clearer
picture.

In both languages, *extension* occurs by opening a mapping immediately following
a tuple expression (i.e., an expression naming or creating a tuple). For example:

```yaml
parent_tuple {
  new_key: 'new value',
  old_key: 'new overriding value',
}
```

Yamlet differs from GCL here by adopting Python’s `key: value` mapping syntax
rather than GCL’s `key = value`. This is a crucial difference, as GCL maintains
a distinction between `old_key { ... extension ... }` and
`old_key = { ... override ... }`, which in Yamlet would need to be accomplished
by replacing the old dictionary with a new *expression,* not tuple.

However, in most cases, you want nested tuples within a child to extend the
identically named tuples in the parent. This is easy to express in Yamlet, and
can be done in several ways.

The first of these is just as above, more GCL-style:

```yaml
child_tuple: !expr |
  parent_tuple {
    new_key: 'new value',  # Python dicts and YAML flow mappings require commas.
    old_key: 'new overriding value',  # String values must be quoted in Yamlet.
  }
```

This example uses a literal-style scalar (denoted by the pipe character, `|`)
so that the YAML parser correctly reads the Yamlet expression snippet.

Quoting the entire expression by any other means is equally valid, but probably
much harder to read.

Another approach is to explicitly denote the tuple composition using the
`!composite` tag, which was created for that purpose:

```yaml
child_tuple: !composite
  - parent_tuple  # The raw name of the parent tuple to composite
  - new_key: new value  # This is a mapping block inside a sequence block!
    old_key: new overriding value  # Note that normal YAML `k: v` is fine.
```

Both examples above behave identically.

Depending on how well your eyes are trained on YAML vs GCL, you may prefer one
style to the other. A further option is to use a flow mapping for the extension
fields. This makes it look closer to the GCL syntax while still allowing YAML
tags and unquoted (plain-style) values. Plain style is not allowed in Yamlet
mapping expressions; unquoted words are assumed to be identifiers.

This approach looks like this:

```yaml
child_tuple: !composite
  - parent_tuple  # The raw name of the parent tuple to composite
  - {
    new_key: new value,  # A comma is now required here!
    old_key: new overriding value  # Plain style is still allowed.
  }
```

Once again, all these examples behave the same, and in fact, the YAML parse for
the latter two snippets is identical.

As mentioned, any nested tuples appearing both within the first element of the
composite operation (`parent_tuple`) and the second element (the inline mapping)
will be extended in the same way.

For the morbidly curious, strictly replacing a tuple in Yamlet (i.e. overriding
a nested tuple rather than extending it) would look something like this:

```yaml
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
        { t2_only_key2: 'Second value that only appears in t2' }
    sub2:
      t2_only_key3: Nested value only in t2
```

In this case, the `sub` tuple is overridden, while `sub2` is extended.
Any nested tuples can be extended or overridden depending on how you structure
the composite operation.

Note that there are usually several ways of expressing a tuple composition in
Yamlet; you can typically use any of YAML's means of expressing the mapping
node of your choosing, or use a Yamlet `!expr` expression and dict literal to
denote the same thing. In this case, however, Yamlet's mapping syntax lacks a
clean way to mark a nested tuple as an override rather than an extension.

There are, however, ways of accomplishing this. The following snippet would
technically have the same effect:

```yaml
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
```

In this case, evaluation of the nested tuple is deferred within the child using
an identity function, specifically `[x][0]`. This is not exactly recommended
behavior, though you could accomplish this more cleanly by adding an identity
function through your `YamletOptions` and then passing the nested tuple to it.

### File Imports

Importing allows you to assign the structured content of another Yamlet file to
a variable:

```yaml
t1: !import my-configuration.yaml
```

The example above reads `my-configuration.yaml` and stores its content in `t1`.
Importing is actually deferred until data from the file is accessed, so you
may import as many files as you like, import files that don't exist, import
yourself, or import files cyclically—errors will only occur if you try to
access undefined or cyclic values within those files.

### Lambda Expressions

Lambda expressions in Yamlet are read in from YAML as normal strings, then
executed as Yamlet expressions:

```yaml
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
```

### Custom Functions

In addition to lambdas, you can also directly expose Python functions for use
in Yamlet configurations. For example:

```python
loader = yamlet.Loader(YamletOptions(functions={
    'quadratic': lambda a, b, c: (-b + (b * b - 4 * a * c)**.5) / (2 * a)
}))
data = loader.load('''
    a: 2
    b: !expr a + c  # Evaluates to 9, eventually
    c: 7
    quad: !expr quadratic(a, b, c)
    ''')
print(data['quad'])  # Prints -1
```

With this approach, you can define custom functions for use in Yamlet
expressions, which can lead to even more expressive configuration files.


### GCL Special Values

In addition to `up` and `super`, GCL defines the special values `null` and
`external`. Yamlet has rudimentary support for these.
 - `external` evaluates to `external` when used in any operation. Requesting
   an external value explicitly results in an error. The observable behaviors
   of this value are the default behaviors for using any undeclared value in
   Yamlet, so unless I've missed something, `external` is not worth using.
 - `null` removes a key from a tuple, omitting it in compositing operations
   unless it is added again later by an overriding tuple composition.
   - Because of this behavior, having `null` assigned to a tuple key is not
     the same as not having that key in the tuple. A `null` value still counts
     toward the `len()` of a tuple, for example, until after composition.

As a simple example of `null`, consider the following:

```yaml
t1:
  key_to_keep: present
  key_to_delete: also present
deleter:
  key_to_delete: !null
t2: !expr t1 deleter
t3: !expr t1 t2
```

In the above example,
 - `t1` has both `key_to_keep` and `key_to_delete`
 - `t2` has *only* `key_to_keep`
 - `t3` has *both* `key_to_keep` and `key_to_delete` once again. This is because
   the key was *missing* from `t2`, not `null` in it.
 - `len(t1)` is 2.
 - `len(t2)` is 1.
 - `len(deleter)` is also 1.
 - `len(t3)` is again 2.

### Error Reporting

Yamlet is pretty good about telling you where a problem happened by converting
the Python stack trace into Yamlet traces, showing the lines involved in
evaluating an expression. You can also directly query Yamlet's
provenance information to discover where a value came from.

## Caveats

### Yamlet is an Extension of YAML

Yamlet is built on top of YAML, meaning that the first tool to parse your
configuration file ***is** a YAML interpreter,* namely Ruamel. The facilities
offered by Yamlet will only work for you if you can convey your expression
strings through Ruamel.

To help with this, Yamlet offers separate tags for `!fmt`
(formatting string values) and `!expr` (general expression evaluation).

There are there because if you try to write this:
```yaml
my_string: !expr 'my formatted string with {inlined} {expressions}'
```
...you are NOT going to get a string! Ruamel will interpret the string value,
removing the single quotes and handing Yamlet a bunch of drivel.

The `!fmt` tag works around this by treating the entire Ruamel value as a
string literal. Alternatively, you can use a literal style block:

```yaml
my_string: !expr |
  'my formatted string with {inlined} {expressions}'
```

At the time of writing, this is the only way to trigger literal style for a
YAML value. I can’t achieve this behavior directly through a tag implementation.

### Map Literals in Yamlet Expressions

Yamlet mappings (tuples, dictionaries) resemble YAML mappings but have slight
differences:

```yaml
my_yamlet_map: !expr |
  {
    key: 'my string value with {inlined} {expressions}',
    otherkey: 'my other value'
  }
```

This is because the Yamlet uses the Python parser to handle expressions,
including flow mappings, which are based on Python dicts. I have taken the
liberty of allowing raw names as keys (per YAML) without unpacking them
as expressions (per Python). To use a variable as the key, you would have to
say `'{key_variable}': value_variable`, but note that the `key_variable`
must be available in the compositing scope (the scope containing the mapping
expression) and CANNOT be deferred to access values from the resulting tuple.

The values within a Yamlet mapping, however, *are* deferred, with the exception
of nested mappings, which are treated as part of the current mapping expression.

For your curiosity, a dynamic key would look like this:

```yaml
static_key: dynamic
tup: !expr |
    { '{static_key}_key': 'value' }
```

The above example would define `dynamic_key` within the `tup` tuple.
Note that other values defined in that mapping would be inaccessible
for use in keys; attempting to access them would result in an error
or a different value being pulled in than the one you might expect.

This setup means that Yamlet mappings are neither pure Python dict literals
nor pure YAML mappings. They are not like Pthon literals because identifiers
(`NAME` tokens) used as keys are not treated as variables. They are also not
YAML flow mapping literals, because every value is a raw Yamlet expression in
which operators can be used and strings must be quoted.

One additional difference from YAML flow mappings is that all keys must have
values; you may not simply mix dict pairs and set keys (YAML allows this;
Python and Yamlet do not).

### Scoping Quirks

Tuples (GCL or Yamlet dicts) inherit their scope from where they are defined.

```yaml
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
```

This example contains four tuples; let's start by examining the first two,
`tuple_A` and `tuple_B`. The latter is *nested* within the former, but does
not inherit from it. That is, there’s no composition at this point, so
`super` is undefined. But due to the nesting, `tuple_B.up` refers to `tuple_A`,
so `tuple_B.value` evaluates to `Apple Banana`.

It gets complicated as we do composition.

Here, `tuple_C` is defined as a specialization of `tuple_A`, where `fruit`
is overridden, and `tuple_B` is extended in much the same way as `tuple_A`.
Because composition is involved, the `super` of `tuple_C` becomes `tuple_A`,
and the `super` of its nested tuple, `tuple_C.tuple_B`, in turn becomes
`tuple_A.tuple_B`. Expressions from each `super` tuple will be inherited by
their respective children, but will be re-evaluated in the new scope.
That means expressions that reference variables (or even keywords such as `up`
and `super` themselves) will be re-evaluated based on the new values
within `tuple_C`.

Because `fruit` is overridden in the inheriting scope (`tuple_C.tuple_B`), and
also in the enclosing scope thereof, the expression in `tuple_A.tuple_B.value`
takes on an entirely new meaning in the context of `tuple_C.tuple_B`'s scope.
The resulting value in that context is `Cherry Blueberry`.

Thus, `tuple_C.tuple_B.value3` will evaluate to
`Apple Banana  -vs-  Cherry Blueberry`.

All of these values are accessible from the innermost inheriting scope,
`tuple_C.tuple_B`. In that scope, `value2` will evaluate to
`Apple Banana Blueberry Cherry`, representing the values from the `super` tuple
pair first, followed by the values from the inheriting tuple pair.

It’s worth noting that `super.up.fruit` is equivalent to `up.super.fruit`.

## Differences from GCL

### Missing Features

There are a few features present in GCL that Yamlet currently doesn’t implement:
- Assertions are not yet supported.
- Additional builtin functions (`substr`, `tail`, etc.).
- GCL-style (C++/C-style) comments cannot be used anywhere in Yamlet.
  Yamlet uses Python/YAML-style comments, as handled by Ruamel.
- The `args` tuple is not supported. This would ideally be the responsibility
  of a command-line utility that preprocesses Yamlet into some other format
  (such as Protobuf).
- Support for `final` and `local` expressions is missing.
  The language might be better without these... though adding them could create
  a way to reliably pre-evaluate entire Yamlet files into other formats.

### Improvements Over GCL

Yamlet tracks all origin information, so there's no need for a separate utility
to trace where expressions came from. Consequently, you may chain `super`
expressions and it will "just work." You can also invoke `explain_value` in any
resulting dictionary to obtain a description of how a value was computed.

From the included example, `print(t['childtuple'].explain_value('coolbeans'))`
will produce the following dump:

```
`coolbeans` was computed from evaluating expression `'Hello, {subject}! ' + 'I say {cool} {beans}!'` in "yaml-gcl.yaml", line 4, column 14
     - With lookup of `subject` in this scope in "/home/josh/Projects/Yamlet/yaml-gcl2.yaml", line 2, column 3
     - With lookup of `cool` in this scope in "/home/josh/Projects/Yamlet/yaml-gcl2.yaml", line 2, column 3
     - With lookup of `beans` in this scope in "/home/josh/Projects/Yamlet/yaml-gcl2.yaml", line 2, column 3
```

Be advised that a complex Yamlet program can generate tens of thousands of lines
of traceback for a single value... so don't get carried away. I suggest leaning
on user-defined functions rather than miles of inter-tuple dependencies.

## Differences from the Rest of the Industry

Yamlet is probably the only templating or expression evaluation engine that
doesn't use jq. If you want to use jq, you can create a function that accepts
a jq string and use Yamlet's literal formatting to insert values into the string.

Yamlet shares a more procedural syntax with GCL, and supports basic arithmetic
operations and several built-in functions, with more likely to be added in the
future.

A Yamlet configuration file (or "program," as GCL calls its own scripts) doesn't
really need jq, because you can just invoke custom routines in it using a more
traditional, functional syntax.

Additionally, Jinja, a popular templating engine, does not pair well with YAML
because Jinja is designed for manipulating lines of text, while YAML relies on
indentation as part of its syntax. Import statements in Yamlet work
differently: they import the final tuple value, not raw lines of
unprocessed text.

## What's in a Name?

Who knows! The name "Yamlet" might play on "JSonnet," drawing on a sort of
Shakespearean motif around the name "Hamlet." It might also be a Portmanteau of
"YAML" and "template," or, more obscurely, some amalgam of "YAML" and "Borglet."
Perhaps it plays more directly on "applet" and how one might write one in YAML.
Or maybe it's simply the product of whatever sort of fever dream leads to the
inception of a tool such as this. Regardless, rest assured that a rose by any
other name would still smell as much like durian.
