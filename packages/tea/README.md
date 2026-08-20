# packages/tea

The Elm architecture, first edition: a model type, a message type, two pure
functions, and a widget tree that is data all the way down.

```dawn
use tea/app.{App, step}
use tea/widget.{Widget, Text, Row, Button}

impl App[Counter] {
  type Msg = CounterMsg
  fn update(m: Counter, msg: CounterMsg) -> Counter = ...
  fn view(m: Counter) -> Widget[CounterMsg] = ...
}
```

## What the tree holds, and what it never holds

`Widget[M]` is a plain ADT: `Text`, `Styled`, `Row`, `Column`, and
`Button(label, on_press: M)`. The interactive leaf carries the *message* an
interaction means, never a callback. That is a load-bearing restriction, not a
style choice: a function field would cost the tree its structural `==`
(functions cannot be compared), and `==` is what makes a view test a single
assertion (`view(m) == expected_tree`) and future frame-diffing thinkable.
The driver loop is the only place a message turns into anything.

## Purity split

`update`, `view`, `render`, and `step` are pure by signature; the package
contains no `!io` at all. The event loop belongs to the application's `main`:
read input, parse it into a message yourself, `step`, print the frame. v1 is
line-mode interaction (no raw terminal, no subscriptions, no `Cmd`); when a
real app needs commands, the associated-effect work is where they grow, with
this trait as the consumer justifying it.

## Rendering

`render` is layout in one sentence each: `Row` joins children with one space,
`Column` with one newline, `Button` shows `[label]`, `Styled` wraps in ANSI
SGR codes (`Plain` is the identity and emits nothing). `clear_screen()` returns
the redraw escape sequence; printing it is the caller's business.

## Diffing

`diff(old, new)` computes the difference between two widget trees as a list
of patches, and `apply(old, patches)` replays it; the contract is
`apply(old, diff(old, new)) == new`, and equal trees diff to the empty list.
A patch is an address (`path`, the chain of child indices; a `Styled` child
is index 0) plus one of four ops: `Replace`, `SetStyle`, `AppendKids`,
`TruncateKids`. Locality is the point: an unchanged sibling is never
mentioned by any patch. Child lists diff unkeyed, Elm-style: pairwise by
index with one tail append or truncate. A middle deletion therefore rewrites
the tail pairwise; that cost is pinned by a test rather than hidden, and keyed
diffing waits for a consumer that measures it as pain.

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

## Worked example

`examples/projects/tea_todo` is a complete interactive todo list over this
package (add, toggle, delete, quit): `todo.dawn` is the pure half with update
and snapshot tests, `main.dawn` is the whole io surface. CI drives a full
session through it byte-for-byte via the example main contract.
