# gate-map

"I changed this file. Which gates can see it?" Ask the tool rather than
remembering.

```
scripts/gate-map/gatemap.py selfhost/src/main.dawn
scripts/gate-map/gatemap.py --changed origin/main
scripts/gate-map/gatemap.py --compiler-inputs # stable selfhost compiler input manifest
scripts/gate-map/gatemap.py --labels        # which differential owns which label
scripts/gate-map/gatemap.py --unseen        # paths no gate watches
scripts/gate-map/gatemap.py --check         # what CI runs
scripts/gate-map/plan.py --event pull_request --base <sha>  # which gates.yml jobs a PR runs
scripts/gate-map/plan.py --check-wiring --selftest          # what tree-policy runs for it
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

## Five files

| file | what it is |
|------|------------|
| `gatemap.py` | the tool: derivation rules, the mutant set, `--check` |
| `plan.py` | the pull-request tier: the gates.yml jobs a diff can reach |
| `mutants.txt` | which assertion each mutant reddens, and which one owns it |
| `unseen.txt` | a ratchet of the paths no gate watches, with a checked reason each |
| `fixtures.txt` | the failures above, replayed on the trees they happened on |

## The pull-request tier

Since 2026-09-23 a pull request runs only the gates.yml jobs this map says
can see its diff; a push to main still runs all of them, and a release only
reads main. `plan.py` imports the Map rather than parsing the report above,
and falls back to every job whenever the map's premise is not known to hold:
a non-PR event, no base, a failed or empty diff, a path under the compiler,
std, packages, launcher, workflows, this directory or the seed and bootstrap
scripts, a map that fails or times out, an unseen path, or a deleted one. Its
module docstring gives the reason for each; its self-test removes each one in
turn and requires a case to go red. `--check-wiring` holds every gates.yml
job to `needs: [plan]` and an `if:` that tests its own id.

Before any of that, the plan job asks whether the head commit carries a
verified `gates/maintainer` status (`scripts/gates-external/release_evidence.py
--external-only`, the release guard's own checks). If it does, the plan is
`all=false`, `jobs=[]` and every gate job skips, on a pull request or a push:
the signed external run of that exact commit already was the whole set. A
rebased pull request has a new head sha with no status, so it plans as
usual; a fork's pull request never has one. `--check-wiring` also holds the
evidence step, the `head` input and the token scopes it needs, and
`--selftest` runs the plan job's two shell steps against a stub `gh`
(accepted, a person's status, a status pointing at a ci.yml run, no status,
an API outage, no head sha).

A path of the `unread` kind (below) is the one unseen path that does not
force the whole set: it selects no job, because the map has read every script
that could open it and none does.

Like `gatemap.py`, `plan.py` is exempt from rules A and B: it names paths to
describe them, and scraping it would record the plan job as reading every
seed pin.

## Harness directories, file by file

Rule A used to hand a step the whole directory of every script it runs. For
`scripts/incremental-semantics-contract/`, 56 harnesses run by 69 steps in 29
jobs, that made every file there every job's code, and a harness-only pull
request such as #164 still ran 30 of 39 jobs (#169). A step under `scripts/`
now owns the files its scripts reach, and the edges are parsed from the
scripts, never guessed from names or directories:

| edge | read from | example |
|------|-----------|---------|
| runs | the step's `run:` line, and scripts those scripts run | `python3 scripts/x/check.py` |
| imports | Python `import m` / `from m import f`, beside the importer or on a `sys.path` entry it adds | `from cold import ROOT, edit, run` |
| sources | shell `source` / `.` | `source "$root/scripts/mutant-coverage/shard.sh"` |
| names | a path inside the directory, built or spelled in the code | `HERE / "x.dawn.txt"`, `Path(__file__).with_name("x")`, `"$here/x"`, `("A.java", "B.java")` |
| includes | quoted C `#include` in a file already reached | `#include "stubs.h"` |
| project | a harness directory handed to `./bin/dawn`: its SourcePlan inputs | `./bin/dawn test scripts/x` reads `dawn.toml` and `src/` |

Every edge closes over what its target reaches, and a shared file goes to
every step that reaches it: `replay-workloads.dawn.txt` belongs to each step
whose script names it. An import reaches the module's top level plus the
functions the importer takes from it, which is what Python executes; that is
why the 39 harnesses taking `ROOT, edit, run` from `cold.py` do not inherit
the `copytree` in `cold.main`, while the step that runs `cold.py` itself does.
A named sibling script is followed as if run, since naming it is how a harness
runs it.

**Fallback.** When the reader cannot bound what a script reads, that script
gets its whole directory, which is the old rule. The conditions are the
directory used as a value (`shutil.copytree(HERE, ...)`, `cwd=HERE`,
`HERE.glob(...)`, `cd "$here"`, `$here` handed to a program), a name computed
inside it (`HERE / f"{name}.txt"`, `"$here/$prog.dawn"`, a glob), a file that
does not parse, and a language with no reader (anything but `.py` and `.sh`).
The fallback is per script: `prefix.py` copies its directory and gets all of
it, and the harnesses beside it do not. Each fallback states the line that
caused it in its reason, so `gatemap.py <path>` shows why a file went to a
step.

**Unread.** A file in a harness directory that no step reaches either way,
typically a README or a benchmark CI does not run, is recorded in
`unseen.txt` under the kind `unread`. The kind is checked in both directions
(`no-gate` may not claim a path the reader cleared, and `unread` may not claim
one it did not), and plan.py reads it as "selects no job".

Outside `scripts/`, a script still owns only itself, and rule B still reads
path tokens from the scripts a step reaches, now excluding the harness's own
directory, which rule A has already read file by file.

## Changing it

Adding a rule means adding an assertion, and an assertion needs a mutant that
uniquely reddens it, or `--check` refuses the record. Regenerate the red sets
with `--record-mutants` and read the diff; the `owner` and `control` lines stay
a hand edit on purpose, because a recorder that could reassign owners would
launder the collision it exists to catch. This copies
`scripts/pipe-contract/matrix.py`, which solved the same problem first.

Adding a path that nothing watches means adding a line to `unseen.txt` with a
reason. The kind at the front of the reason (`no-gate`, `unread`,
`blind-only`, `tag-only`) is checked against the map, so it cannot go on
claiming something the tree stopped supporting. `--record-unseen` keeps the reasons already
written and marks a new line for you to fill in.

## What it does not promise

`coarse` means "a gate reads this path", not "a gate would notice what you
changed there". The distance between the verdicts is the distance between
strengths of coverage, and the docstring defines each one.

The `selfhost/` project has two roles in prev-diff. Both output legs compile the
same selfhost corpus into their respective directories, so its own project
content receives the ordinary own-content `blind` verdict. Separately, the HEAD
leg must invoke the exact `HEAD_BIN` assigned to `./bin/dawn`. SourcePlan builds
that compiler from a closure rooted at `selfhost`: repo-local string `[deps]`
are followed recursively, every project contributes `dawn.toml` and `src`, and
only the root contributes its optional `dawn.lock`. The closure is derived from
the supplied Tree, including historical fixtures and mutants, without package
names baked into the rule. Lexical escapes, cycles, missing manifests or source
trees, parse failures and unfamiliar dependency forms void the premise instead
of silently dropping an input. Compiler semantic or build-input changes in the
derived closure receive a `coarse` verdict and can move any emit label. Use the
real differential or an unmasked true-parent control to decide whether such a
change needs a declaration.

`--compiler-inputs` writes that derived closure in the exact
`dawn-source-inputs-v1` record format used by `dawn __source-inputs`. The
source-plan contract compares both producers byte for byte, including the
schema header, required and optional kinds, path set and ordering. This keeps
the map's Tree-backed historical derivation tied to the compiler's live
SourcePlan semantics.

The rules can be wrong. Over-claiming is the worse direction, because a map
that says a file is watched when it is not repeats this directory's own subject
one level up, so a rule with a choice to make under-claims and the residue goes
into `unseen.txt` where somebody can read it.
