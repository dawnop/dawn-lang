# gate-map

"I changed this file. Which gates can see it?" Ask the tool rather than
remembering.

```
scripts/gate-map/gatemap.py selfhost/src/main.dawn
scripts/gate-map/gatemap.py --changed origin/main
scripts/gate-map/gatemap.py --labels        # which differential owns which label
scripts/gate-map/gatemap.py --unseen        # paths no gate watches
scripts/gate-map/gatemap.py --check         # what CI runs
```

## Why it exists

Two red builds on 2026-08-11, one root cause: nobody had written down which
gate sees which change, so every batch re-derived it and two derived it wrong.

1. `3c51ae1` pinned a negative control to a whole sentence the std loader
   prints, and `9e64179` rewrote that sentence. Each batch was green alone and
   the pair was red, because a contract script and a compiler module shared a
   string constant and nothing said so. Fixed in `819920e`.
2. `98b9896` rewrote `dawn --help` and `dawnc --help`. It ran doc-check,
   site-dist-diff, run-diff, prev-diff and native-cli-diff, and none of the five
   can see it: the emit labels cover programs the compiler builds, not the
   compiler's own driver modules. The Core golden moved and was re-recorded the
   next commit (`1c29bea`).

Prose about gate boundaries is what rotted into those two failures, so this is
not prose. Everything is recomputed from the tree on every run. The derivation
rules, the four verdicts (`exact`, `coupled`, `coarse`, `blind`) and the file
each rule reads are documented in the module docstring of `gatemap.py`, which
is the authority; this page does not restate them.

## Four files

| file | what it is |
|------|------------|
| `gatemap.py` | the tool: derivation rules, the mutant set, `--check` |
| `mutants.txt` | which assertion each mutant reddens, and which one owns it |
| `unseen.txt` | a ratchet of the paths no gate watches, with a checked reason each |
| `fixtures.txt` | the failures above, replayed on the trees they happened on |

## Changing it

Adding a rule means adding an assertion, and an assertion needs a mutant that
uniquely reddens it, or `--check` refuses the record. Regenerate the red sets
with `--record-mutants` and read the diff; the `owner` and `control` lines stay
a hand edit on purpose, because a recorder that could reassign owners would
launder the collision it exists to catch. This copies
`scripts/pipe-contract/matrix.py`, which solved the same problem first.

Adding a path that nothing watches means adding a line to `unseen.txt` with a
reason. The kind at the front of the reason (`no-gate`, `blind-only`,
`tag-only`) is checked against the map, so it cannot go on claiming something
the tree stopped supporting. `--record-unseen` keeps the reasons already
written and marks a new line for you to fill in.

## What it does not promise

`coarse` means "a gate reads this path", not "a gate would notice what you
changed there". The distance between the verdicts is the distance between
strengths of coverage, and the docstring defines each one.

The rules can be wrong. Over-claiming is the worse direction, because a map
that says a file is watched when it is not repeats this directory's own subject
one level up, so a rule with a choice to make under-claims and the residue goes
into `unseen.txt` where somebody can read it.
