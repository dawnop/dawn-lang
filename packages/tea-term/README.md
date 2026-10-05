# packages/tea-term

The terminal half of the Elm architecture: the widget vocabulary, its DSL, its renderer, the row presenter, routing, and the driver loop.

```dawn
use tea_core/app.{App}
use tea_core/cmd.{Cmd}
use tea_term/step.{step}
use tea_term/widget.{Widget, Text, Row, Button}

impl App[Counter] {
  type Msg = CounterMsg
  type View = Widget[CounterMsg]
  fn update(m: Counter, msg: CounterMsg) -> (Counter, Cmd[CounterMsg]) = ...
  fn view(m: Counter) -> Widget[CounterMsg] = ...
}
```

The `Tree` contract, the reconciler, `trait App` and subscriptions are
`packages/tea-core`'s. `examples/projects/tea_todo` is a complete app:
`todo.dawn` is the pure half with its tests, `main.dawn` the io.

## Widgets

`Widget[M]` is `Text`, `Styled`, `Row`, `Column` and `Button(label, on_press:
M)`. A button holds the message a press means, never a callback, so a tree has
structural `==` and a view test is one assertion: `view(m) == expected`.

`update`, `view`, `render`, `step`, `present` and the routing functions are
pure. The one `!io` is `runtime.run`, the driver loop, which an app hands its
pure hooks: the view, a parser from an input line to a message, its ticks and
when to stop. A `SendMsg` command is one more `update` before the next paint.

## Subscriptions

`run` reads the monotonic clock (std/io's `Clock`), so `Tick(every_ms, msg)`
fires every `every_ms` of elapsed time, typing, updating and painting
included. A tick that a slow turn made late fires once; periods missed whole
are skipped, not delivered in a burst. Before 0.4.0 the loop had no clock and
counted only full poll timeouts, so steady input could hold a timer off
indefinitely.

At end of input the session ends, timers or not: the native backend's poll
answers at once for a closed stream, the loop sees from the clock that the
answer came early, and reads. The JVM backend cannot tell a closed pipe from
a silent one, so there a subscribed app on piped input keeps ticking until
`done`. `run` installs the real clock itself, so its signature has no
`!Clock`. The timing rules are in `runtime.dawn`'s header.

## The DSL

`tea_term/dsl` has lowercase wrappers over the constructors: `text("hi")`,
`bold` / `dim` / `underline`, `button(label, msg)`, `row([...])` and
`column([...])`. `row_do { ... }` / `column_do { ... }` take a block that may
hold `let`s before the child list.

Type arguments flow from the expected type, and a `let` has none: `text("a")`
infers `M` as a list element, a return value or an annotated binding, but not
as a bare segment of a `++` chain. Write a view as annotated `let`s
(`let header: Widget[Msg] = ...`) and join the named parts. And the tail block
is a thunk: `row_do` is for when a statement belongs next to the children,
and never shorter than `row([...])`.

## Rendering and presenting

`render` lays out a tree: `Row` joins children with a space, `Column` with a
newline, `Button` shows `[label]`, `Styled` wraps its child in ANSI SGR codes.
`clear_screen()` is the redraw sequence.

`present(prev, next)` compares two rendered frames row by row and answers the
cursor-addressed bytes that rewrite only the rows that changed, or `""` for an
identical frame. `frame_lines` cuts a frame into rows and `park(nrows)` puts
the prompt below it. The caller keeps the rows it last painted.

## Routing

`route.buttons(w)` lists every button in pre-order, `route.press(w, n)` is the
message of the n-th one (1-based) or `None`, and `route.addressed(w)` keys the
same walk by patch address.

Changes between versions: [CHANGELOG.md](CHANGELOG.md).
