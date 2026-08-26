# packages/tea-term

The terminal half of the Elm architecture: the widget vocabulary, its DSL, its
renderer, the row presenter, routing, and the driver loop. The
vocabulary-free half -- the `Tree` contract, the reconciler, the walk,
`trait App` and subscriptions -- is `packages/tea-core`, which this package
depends on.

```dawn
use tea_core/app.{App}
use tea_term/step.{step}
use tea_term/widget.{Widget, Text, Row, Button}

impl App[Counter] {
  type Msg = CounterMsg
  type View = Widget[CounterMsg]
  effect E = !()
  fn update(m: Counter, msg: CounterMsg) -> Counter = ...
  fn view(m: Counter) -> Widget[CounterMsg] = ...
}
```

## Why two packages

`runtime.run` has an effect row and `use std/io`; a host that is not a terminal
should not have to pull that in to reach a reconciler. A package boundary is
the only thing in the language that says so, and it says it to the machine
rather than to a reader. The split also has one shape forced on it: the orphan
rule is per module, so `impl[M] Tree[Widget[M]]` can only live in the file
declaring `Widget`, which is `widget.dawn` here.

## What the tree holds, and what it never holds

`Widget[M]` is a plain ADT: `Text`, `Styled`, `Row`, `Column`, and
`Button(label, on_press: M)`. The interactive leaf carries the *message* an
interaction means, never a callback. That is a load-bearing restriction, not a
style choice: a function field would cost the tree its structural `==`
(functions cannot be compared), and `==` is what makes a view test a single
assertion (`view(m) == expected_tree`) and future frame-diffing thinkable.
The driver loop is the only place a message turns into anything.

## Purity split

`update`, `view`, `render`, `step`, `present`, and everything in tea_core are
pure by signature; the only `!io` in either package is `runtime.run`, the
driver loop. An app hands `run` its pure hooks (which tree to paint, parse a
line into a message, declare ticks, say when to stop) and owns nothing else.
The view arrives as a hook rather than through the trait because a generic
function cannot do anything with an `A.View`; see tea-core's README.
Still line-mode interaction and still no `Cmd`; when a real app needs
commands, the associated-effect work is where they grow, with this trait as
the consumer justifying it.

## Subscriptions

`Sub[M]` lives in tea_core and is unchanged by the split. What belongs here is
the honesty note the driver owes it: there is no clock in std, so "every n ms"
counts waiting (`stdin_ready` timeouts) rather than wall time, and the caveats
live in runtime.dawn's header.

## Rendering

`render` is layout in one sentence each: `Row` joins children with one space,
`Column` with one newline, `Button` shows `[label]`, `Styled` wraps in ANSI
SGR codes (`Plain` is the identity and emits nothing). `clear_screen()` returns
the redraw escape sequence; printing it is the caller's business.

## Writing views: the DSL spelling

`tea_term/dsl` is lowercase wrappers over the constructors and nothing deeper:
`text("hi")` for `Text(s: "hi")`, `bold`/`dim`/`underline` for the styled
wrappers, `button(label, msg)`, and `row([...])`/`column([...])` with
children as a real list. Containers also have a tail-block spelling,
`row_do { ... }`/`column_do { ... }`, whose block may hold statements
(`let`s) before ending with the child list; for a single expression the
paren spelling is strictly cheaper. Children stay explicit lists on
purpose -- implicit collection was probed and is unreachable by design
(handler evidence settles at the block's creation site).

Two usage taxes, both inference direction, neither specific to the DSL but
both met immediately when writing views:

- Type arguments flow from expected types, and a `let` binding has none.
  `text("a")` infers `M` in list elements, function returns, and annotated
  positions; a bare segment in a `++` chain does not. Shape a view as
  annotated `let`s per segment (`let header: Widget[Msg] = ...`) and
  concatenate the named parts.
- The tail block is a thunk. Reach for `row_do` only when a statement
  belongs next to the children; it never saves characters over `row([...])`.

## Diffing

The reconciler is tea_core's; what lives here is the vocabulary's side of its
contract, the `impl[M] Tree[Widget[M]]` at the bottom of `widget.dawn`. Three
functions: `kids` (a `Styled` has exactly one child, at index 0), `rekid`
(total, so a leaf handed children ignores them and a `Styled` emptied stays
itself), and `relate` (`Styled` pairs answer `Same` or `SelfDiffers` by style,
containers of a kind answer `Same`, everything else is `Unrelated`).

`relate` is short because it is only asked about pairs already known unequal:
`Text` against `Text` and `Button` against `Button` hold nothing to descend
into, so an inequality is theirs and the answer is `Unrelated` whether the
constructors match or not.

## Presenting

The terminal retains no widget tree; what it retains is the rows already on
screen. `present(prev, next)` therefore diffs at the row, not the widget: it
returns the cursor-addressed ANSI bytes that rewrite exactly the rows that
changed (erase first, so shorter rows leave no tail), erases leftover rows
when the frame shrinks, and returns the empty string for an identical frame.
`frame_lines` cuts a rendered frame into rows; `park(nrows)` positions and
clears the prompt row below the frame. All pure: the caller owns the
terminal, keeps the rows it last painted, and only the first paint clears
the screen.

## Routing

A `Button` already carries its message; `route.buttons(w)` gives every
button in pre-order (label and message), and `route.press(w, n)` answers
what pressing the n-th one (1-based) means, or `None`. A line-mode app
wires this into its parse hook (the demo's `press <n>`); a focus model
would walk the same list. `route.addressed(w)` is the same walk keyed by
patch address instead of ordinal, which is what a host that hands back a node
rather than a number would dispatch on.

All three are `tea_core/walk.fold_preorder` plus a match arm, and they are
here rather than in core because core has no way to ask a node for its label.

## Worked example

`examples/projects/tea_todo` is a complete interactive todo list over these
two packages (add, toggle, delete, quit): `todo.dawn` is the pure half with update
and snapshot tests, `main.dawn` is the whole io surface. CI drives a full
session through it byte-for-byte via the example main contract.
