# lsp-sync-bench

Measures how long the language server takes to settle after an edit in the
selfhost workspace, and holds the result to the lines of the 2026-10-19 ruling.
Run it by hand before every release (docs/bootstrap.md); it is not a CI gate,
because the numbers depend on machine load. The method and its reasons are in
[docs/lsp-sync-bench-design.md](../../docs/lsp-sync-bench-design.md).

```
# the jar under test, every scenario and every pub fn of check/types (~6 min)
python3 scripts/lsp-sync-bench/bench.py --jar build/dawn-selfhost.jar --out sync.json

# against the previous release, interleaved edit by edit (~13 min)
python3 scripts/lsp-sync-bench/bench.py --jar build/dawn-selfhost.jar \
    --baseline .dawn/seeds/v0.94.0/seed.jar --out sync.json

# quicker: 30 functions spread over the module, scenarios (b) and (d) only
python3 scripts/lsp-sync-bench/bench.py --jar build/dawn-selfhost.jar --sample 30 --scenarios bd

# the same jar under two collectors, interleaved: compares JVM options, not code
python3 scripts/lsp-sync-bench/bench.py --jar build/dawn-selfhost.jar \
    --baseline build/dawn-selfhost.jar --baseline-jvm='-Xss512m -Xmx2g -XX:+UseSerialGC'

# judge a saved report again, for instance against a changed line
python3 scripts/lsp-sync-bench/bench.py --rejudge sync.json --line L-ws-sig=250

# no JVM: the edit logic, and every anchor still matching exactly once
python3 scripts/lsp-sync-bench/bench.py --self-test
```

Wrap a measuring run in `dcap` on the shared development machine.

## What it does

The workspace is `<root>/selfhost` (`--root`, default this checkout). Six files
are opened (`main`, `front/ast`, `check/checker`, `check/types`,
`driver/analyze`, `jvm/emit`), and every edit is a full-text `didChange`
followed by an unknown request that the server must answer only after the
pending analysis is done:

| scenario | edit | kind |
|---|---|---|
| a | a `let` at the top of `seg_ok` in `driver/analyze` | body |
| b | toggle a defaulted last parameter of `eff_suffix` in `check/types` | signature |
| c | a `let` at the top of `arg_exprs` in `front/ast` | body |
| d | toggle a new `pub type` at the end of `check/types` | type definition |
| sample | toggle the same parameter on each `pub fn` of `check/types` | signature |

Two times per edit: `sync`, until the barrier answers (workspace convergence),
and `edit`, until the edited file's `publishDiagnostics` arrives. The server
publishes an open file as soon as its module is analysed, so `edit` is the
shorter of the two.

Servers start with the options `bin/dawn lsp` uses (`JVM_OPTS`, held equal to
the launcher's by `scripts/check-launcher-jvm-opts.py`); `--jvm` and
`--baseline-jvm` replace them, each as one blank-separated string. After every
recorded edit the server's resident set (`VmRSS`) is read, and at the end of
each session its high-water mark (`VmHWM`), on Linux.

Each scenario session warms up for `--warm` rounds (3) and records `--rounds`
(7); `--passes` (6) fresh sessions give 42 samples per scenario. The sample
takes the median per function, then the median and p90 over functions. All
quantiles are nearest-rank.

Before every round and every sampled function the 1-minute loadavg must be at
most `--load-max` (4); otherwise it waits, `--load-poll` seconds at a time, and
gives up after `--load-timeout` seconds of waiting in total. Every sample
records the loadavg at the moment it was sent.

With `--baseline`, both servers run at once and take turns on the same edits,
swapping who goes first each round; `paired` in the report is subject minus
baseline per round (per function for the sample).

## Lines and exit status

| line | applies to | quantity | limit |
|---|---|---|---|
| L-edit | a, b, c, d, sample | `edit` p90 | 100 ms |
| L-ws-body | a, c | `sync` p90 | 300 ms |
| L-ws-sig | b, sample | `sync` p90 | 300 ms |
| L-ws-type | d | `sync` p90 | 1000 ms |

Only the jar under test is judged. `--line NAME=MS` overrides a line.
Exit 0 when every line holds, 1 when one is crossed, 2 on a usage or harness
error (an anchor that no longer matches exactly once, a server that died),
3 when the load guard times out.

## Output

JSON (to `--out`, else stdout): the jars and their sha256, the configuration,
the load range, per-server `results` (median, p90, min, max, n for `sync` and
`edit`, plus the slowest sampled functions, and `rss`: the median and p90 of
the resident set after recorded edits and the largest session high-water mark,
in MiB), `paired`, the judged `lines`,
`ok`, and every raw sample in `rows`. One summary line goes to stdout when
`--out` is given, to stderr otherwise:

```
lsp-sync-bench: OVER L-ws-sig b sync p90 746>300, ...; sync median/p90 ms: a 99/141, b 719/746, ...; load 1.2-1.6
```

## When an anchor moves

The edits find their sites by name (`fn seg_ok`, `fn eff_suffix`,
`fn arg_exprs`, the `pub fn` list of `check/types`). If a rename makes one
match zero or two times, the run stops with status 2 before any server starts;
point `SCENARIOS` in `bench.py` at an equivalent function and say so in the
release notes, since the numbers are then not comparable with older runs.
