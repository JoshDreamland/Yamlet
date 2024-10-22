# Yamlet: A GCL-like templating engine for YAML

Yamlet is a tool for writing complex configurations in YAML.

It is reminiscent of GCL, but has strict YAML syntax, while offering complex
expression evaluation and templating operations that would have otherwised
required an engine such as Jinja.

YAML itself doesn't support even simple operations such as string concatenation,
so a common wishlist item for people is the ability to use a YAML anchor to
extend one value inside another.

E.g.
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
I can say for `gcl.py` from the Pip repo.

(Note for the uninitiated to GCL: A "Tuple" is the equivalent of a dictionary.)

This tool is lightweight at the moment and kind of fun to reason about,
so drop me issues or feature requests and I'll try to attend to them.

The biggest change that would make this project nicer is if YAML supported
raw strings (literal style) for specific constructors without the use of a
specific style token. In particular, it's annoying having to insert a pipe
and newline before any expression that you'd like to be evaluated GCL-style
instead of YAML style. Similarly, it would be nice if I could define an
`!else:` constructor that starts a mapping block, or revise the spec to
disallow colons at the end of tags (where followed by whitespace). Until then,
the best workaround I can recommend is habitually parenthesizing every Yamlet
expression, and putting spaces after all your tokens like it's the 80s.

To help work around this, I've added `!fmt` and `!composite` tags on top of
the core `!expr` tag so that the YAML parser can handle the string interpreting
and nested tuple parsing. So in the below examples, I could have used
`coolbeans: !fmt 'Hello, {subject}! I say {cool} {beans}!'` instead of that
pipe nonsense if I didn't want to show off string concatenation explicitly.

I have also added a stream preprocessor that replaces `!else:` with `!else :`
for when someone inevitably forgets or doesn't read this.


## Installation

Yamlet is not currently available on Pip. It is a single Python file; you may
copy it into your project wherever you like.

I will attempt to publish to PyPI sooner or later.


## Features
This is a summary of the features showcased above:
- [String formatting](#string-formatting)
- [GCL-Like tuple composition](#tuple-composition)
- [Conditionals as seen in procedural languages](#conditionals)
- [File Imports](#file-imports) (to allow splitting up configs or splitting out templates)
- [Lambda expressions](#lambda-expressions)
- [Custom functions](#custom-functions) (defined in Python)
- Explicit [value referencing](#scoping-quirks) in composited tuples using
  `up`/`super`
  - `up` refers to the scope that contains the current scope, as in nested
     tuples.
  - `super` refers to the scope from which the current scope was composed,
     as in the template from which some of its values were inherited.


## Examples
As a whirlwind tour, consider a main file, `yaml-gcl.yaml`:
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

loader = yamlet.Loader()
t = loader.load_file('yaml-gcl.yaml')
print(t['childtuple']['coolbeans'])
print(t['childtuple2']['coolbeans'])
```

Will print the following:
```
Hello, world! I say cooool beans!
Hello, world! I say awesome sauce!
```

You can try this out by running `example.py`.

Flipping the definitions of `childtuple` and `childtuple2` to instead read
`t2 t1.tuple` and `t1.tuple2 t2` would instead print, respectively,
`cooool sauce` and `awesome beans`, which would be upsetting, so don't do that.
I mean, that's by design; this is how GCL templating works. Each tuple you
chain onto the list overwrites the values in the previous tuples, and then
expressions inherited from those tuples will use the new values.

Placing tuples next to each other in Yamlet composites them. For example, you
can use `my_template { my_key: overridden value }` to *instantiate* the tuple
`my_template` and override `my_key` within that tuple with a new value.

I'll break this down better in these next sections.

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

Note that specifically because of the aforementioned problems, YAML actually
requires you to have a space between the `!else` tag and the following colon.
However, Yamlet's stream preprocessor handles this for you, at the cost of any
data that would otherwise contain the string `"!else:"`... which should be a
non-issue, right?

### String Formatting

Yamlet offers several syntaxes for string composition.

```yaml
subject: world
str1: !expr ('Hello, {subject}!')
str2: !expr ('Hello, ' + subject + '!')
str3: !fmt 'Hello, {subject}!'
```

All of these strings will evaluate to `Hello, world!`.

The next section explains how to create a template that lets you modify the
value of `subject` from within your program or within other context in Yamlet.

### Tuple Composition

In GCL, the basic unit of configuration is a tuple, and templating happens
through extension. Yamlet inherits this behavior. This is the hardest behavior
to get one's head around, so I'll push the system to its limits to try to paint
a clearer picture.

In both languages, *extension* occurs by opening a mapping immediately following
a tuple expression (an expression naming or creating a tuple). An example:

```yaml
parent_tuple {
  new_key: 'new value',
  old_key: 'new overriding value',
}
```

Yamlet is different from GCL here, in that it inherits Python and YAML's mapping
syntax of `key: value` rather than GCL's of `key = value`. This is crucial as
GCL maintains a distinction between `old_key { ... extension ... }` and
`old_key = { ... override ... }`, which would need to be accomplished in Yamlet
by replacing the old dictionary with a new expression completely.

In most cases, however, you want tuple values nested within a child to extend
the identically named tuple values nested within its parent. This is simple to
express in yamlet, and can be done several ways.

The first of these is just as above, GCL-style:
```yaml
child_tuple: !expr |
  parent_tuple {
    new_key: 'new value',  # Python dicts and YAML flow mappings require commas.
    old_key: 'new overriding value',  # String values must be quoted in Yamlet.
  }
```

In this case, a literal style scalar is used (denoted by the `|` pipe character)
so that the YAML parser correctly reads the Yamlet expression snippet.

Quoting the entire expression by any other means is equally valid, but probably
much harder to read.

Another approach is to explicitly denote the tuple composition using the
`!composite` tag for that purpose:
```yaml
child_tuple: !composite
  - parent_tuple  # The raw name of the parent tuple to composite
  - new_key: new value  # This is a mapping block inside a sequence block!
    old_key: new overriding value  # Note that normal YAML `k: v` is fine.
```

The behavior of the above two examples is identical. Depending on how well your
eyes are trained on YAML vs GCL, you may prefer one to the other. A further
option I sometimes use is to use a flow mapping around the extension fields.
This makes it look closer to the GCL syntax while still allowing YAML tags
and unquoted (plain-style) values. Plain style is not allowed in Yamlet
mapping expressions; unquoted words are assumed to be identifiers.

That looks like this:
```yaml
child_tuple: !composite
  - parent_tuple  # The raw name of the parent tuple to composite
  - {
    new_key: new value,  # A comma is now required here!
    old_key: new overriding value  # Plain style is still allowed.
  }
```

Once again, the behavior of all of these (and indeed, the parse of the latter
two snippets) is identical.

As mentioned, any nested tuples within both the parent and the second element
of the composite operation will likewise be extended.

For the morbidly curious, replacing a tuple entirely in Yamlet would look
something like this, where `sub` is overridden:

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
        { t2_only_key2: 'Second value that only appears in t1' }
    sub2:
      t2_only_key3: Nested value only in t2
```

Note that there are usually several ways of expressing a tuple composition in
Yamlet; you can generally use any of YAML's means of expressing the mapping or
sequence node of your choosing, or use a Yamlet `!expr` expression to denote the
same thing, but in this case, Yamlet's mapping syntax lacks a clean way to mark
a nested tuple as an override as opposed to an extension.

There are, however, ways of accomplishing this. The following snippet would
technically have the same effect:

```yaml
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
```

In this case, evaluation of the nested tuple is deferred within the child using
an identity function, specifically `[x][0]`. This is not exactly recommended
behavior, though you could accomplish similar by adding an identity function
through your `YamletOptions` class and enclosing the tuple in that.

### File Imports

Importing assigns the structured content of another Yamlet file to a variable.

```yamlet
t1: !import my-configuration.yaml
```

The above example reads `my-configuration.yaml` and stores it in `t1`.
This operation is actually deferred until data is accessed within the file,
so you may import as many files as you like, import non-existing files,
import yourself, or import files cyclically, and you'll only see an error
if accessing values within that file leads to undefined behavior (such as if
the file didn't exist, or values within that file refer to themselves or
values in other files cyclically).

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

You can also directly expose Python functions for use in Yamlet configurations.

```py
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


## Strengths
Because this is baked on top of YAML in Python, we have pretty good power and
modularity. At the core of this project is Ruamel, which handles the original
file parsing. Python handles the expression parsing. I do minor preprocessing
on both the YAML file and Python expressions to work around a YAML quirk and
to implement composition as an implicit operator.

### Error reporting
Yamlet is pretty good about telling you where a problem happened by converting
the Python stack trace into a Yamlet trace showing lines within the file that
were involved in evaluating an expression. You can also directly query the
provenance information to learn where a value came from.

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
```yaml
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
including interpreting flow mappings (which are based instead on Python dicts).
I have taken the liberty of allowing raw names as the key (per YAML) without
unpacking these as expressions (per Python). To use a variable as the key, you
can say `'{key_variable}': value_variable`, but note that the `key_variable`
must be available in the compositing scope (the scope containing the mapping
expression) and CANNOT be deferred to access values from the resulting tuple.
The values within a Yamlet mapping, however, *are* deferred.

So the real weirdness here is that this isn't a Python dict literal, because
name variables are not variables, and this isn't a YAML mapping literal, because
every value is a raw Yamlet expression, wherein strings must be quoted.
An additional difference from YAML flow mappings is that all keys must have
values; you may not simply mix dict pairs and set keys (YAML allows this,
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

Note that we have four tuples here, starting with a very vanilla `tuple_A` and
`tuple_B`, where `tuple_B` is nested within `tuple_A`. In this context, there is
no composition, so there is no `super`. Because of the nesting, `tuple_B.up`
refers to `tuple_A`. So its own `value` field, `tuple_A.tuple_B.value`,
will show `Apple Banana`.

It gets complicated as we do composition. I am using the GCL style mappings
in the example above, as seeing the nested tuple overrides at the same
indentation was a bit jarring for the purposes of an example.

Here, `tuple_C` is defined as a specialization of `tuple_A`, with an override
extending `tuple_A.tuple_B` in the same way. Therefore, the `super` of `tuple_C`
is `tuple_A`, and the `super` of its nested tuple, `tuple_C.tuple_B`, is in
turn `tuple_A.tuple_B`. Values in each will be inherited from their `super`
in this new context: expressions that reference variables, or even keywords
such as `up` and `super` themselves, will be re-evaluated in the new scope.

Because `fruit` is overridden in the child scope, and also in the enclosing
scope, the expression in `tuple_A.tuple_B.value` takes on an entirely new
meaning in the context of `tuple_C.tuple_B`'s scope, and so the resulting
value is `Cherry Blueberry`. 

Thus, `tuple_C.tuple_B.value3` will evaluate to
`Apple Banana  -vs-  Cherry Blueberry`.

All of these values are available from the innermost inheriting scope, 
`tuple_C.tuple_B`. In that scope, `value2` will evaluate to
`Apple Banana Blueberry Cherry`—the values from the `super` pair of tuples
appear first, then the two values from the inheriting pair.

Note that `super.up.fruit` is identical in behavior to `up.super.fruit`.

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
- GCL-style (C++/C-style) comments cannot be used anywhere in Yamlet.
  Yamlet uses Python/YAML-style comments, as implemented in Ruamel.
- Support for the `args` tuple. This would ideally be the responsibility of
  a command-line utility that preprocessed this into proto or whatever.
- Support for `final` and `local` expressions. The language might be better
  without these...

### Improvements over GCL
Yamlet tracks all origin information, so there's no need for a separate utility
to tell you where an expression came from. Consequently, you may chain `super`
expressions within Yamlet and it will "just work." You can also invoke
`explain_value` in any resulting dictionary to retrieve a description of how the
value was determined. This feature could use more testing and debugging for
beautification purposes.

From the included example, `print(t['childtuple'].explain_value('coolbeans'))`
will produce the following dump:

```
`coolbeans` was computed from evaluating expression `'Hello, {subject}! ' + 'I say {cool} {beans}!'` in "yaml-gcl.yaml", line 4, column 14
     - With lookup of `subject` in this scope in "/home/josh/Projects/Yamlet/yaml-gcl2.yaml", line 2, column 3
     - With lookup of `cool` in this scope in "/home/josh/Projects/Yamlet/yaml-gcl2.yaml", line 2, column 3
     - With lookup of `beans` in this scope in "/home/josh/Projects/Yamlet/yaml-gcl2.yaml", line 2, column 3
```

Be advised that a complex Yamlet program can generate tens of thousands of lines
of traceback for a single value... so don't get carried away. Use the built-in
function utility.

## Differences from the rest of industry
Yamlet is probably the only templating or expression evaluation engine that
doesn't use jq. If you want to use jq, you can create a function that accepts
a jq string and use Yamlet's literal formatting to put values in the string.

Yamlet shares a more procedural syntax with GCL, as well as support for basic
arithmetic operations and a few built-in functions, which I am likely to extend
later.

A Yamlet configuration file (or "program," as GCL calls its own scripts) doesn't
really need jq, because you can just invoke routines in it functionally.

It's also worth pointing out that Jinja does not pair well with YAML because
Jinja lends itself to cutting and pasting lines of file, and YAML uses indent
as a form of syntax. Import statements in Yamlet import the final tuple value,
not a chunk of unprocessed lines of a text file.

## What's in a name?
Who knows! Maybe it plays on "JSonnet" by building a sort of Shakespearean motif
around the name "Hamlet." Maybe it's a Portmanteau of "YAML" and "template," or,
more obscurely, some amalgam of "YAML" and "Borglet."
Maybe it plays more directly on "applet" and how one might write them in YAML.
Maybe it's simply the product of whatever sort of fever dream leads to the
inception of a tool such as this. Regardless, rest assured that a rose by any
other name would smell as much like durian.
