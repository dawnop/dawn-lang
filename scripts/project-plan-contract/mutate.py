#!/usr/bin/env python3
"""Apply one ProjectPlan capture mutant's edit to a copy of the repository tree.

    scripts/project-plan-contract/mutate.py <mutation> <tree-root>

The anchors used to be two Python heredocs in run.sh, each refusing a moved
anchor only when the lsp-workspace job reached that mutant, after building
the captured probe. driver/analyze.dawn and lsp/server.dawn change with most
loader and editor work, so a drifted anchor surfaced as a red job long after
the edit that moved it (#277). Declared here, in the registry shape
mutation-anchor-preflight.py discovers, the same anchors have two consumers:
run.sh applies one mutant per private selfhost copy, and the preflight proves
every one exactly-once before any build.

The loader heredoc also rewrote the captured probe's manifest, because run.sh
copied the probe to `<tree>/probe`, where its `../../../selfhost` dependency
no longer reached the mutant compiler. run.sh now copies the probe to the
path it has in the checkout, where the manifest resolves as written, so there
is nothing left to rewrite and no anchor to register for it.

A mutation is an ordered tuple of edits, each applied to the text the
previous one left, with paths relative to the tree root.
"""

from pathlib import Path
import sys

ANALYZE = "selfhost/src/driver/analyze.dawn"
SERVER = "selfhost/src/lsp/server.dawn"

MUTATIONS = {
    # The loader both entries go through: `load_entries_over` for a command and
    # the editor's `load_entries_reusing`, which reuses unchanged parses.
    "fresh-replan-loader": ((
        ANALYZE,
        '''pub(pkg) fn load_entries_reusing(
  plan: ProjectPlan,
  entries: List[String],
  over: Map[String, String],
  previous: ParseMemo
) -> ReusingLoad !Fs !Env !io =
  resolve(
    plan.source.source_root,
    entries,
    planner_diags(plan.source.diags),
    plan.source.pkgs,
    over,
    entry_file(plan),
    previous
  )
''',
        '''pub(pkg) fn load_entries_reusing(
  plan: ProjectPlan,
  entries: List[String],
  over: Map[String, String],
  previous: ParseMemo
) -> ReusingLoad !Fs !Env !io = {
  # `project_plan` is `!Proc` since io.run moved onto the effect, and this row
  # is not; answering it here keeps the mutation to one function. `Env` is on
  # the row already: `resolve` reaches io.cwd whether or not this replans.
  let fresh = io.with_proc_real(() => project_plan(plan.source.target))
  resolve(
    fresh.source.source_root,
    entries,
    planner_diags(fresh.source.diags),
    fresh.source.pkgs,
    over,
    entry_file(fresh),
    previous
  )
}
''',
    ),),
    "fresh-completion": ((
        SERVER,
        'completions_at(qc, analysis.modules, d.text, pos_offset(d, params))',
        'completions_at(qc, None, d.text, pos_offset(d, params))',
    ),),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
