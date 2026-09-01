#!/usr/bin/env python3
"""Keep the LSP workspace design's case and mutant counts executable."""

import argparse
import ast
from pathlib import Path
import re
import shlex
import sys


ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/lsp-workspace-design.md"
RUNNER = ROOT / "scripts/lsp-workspace-contract/run.sh"
WORKSPACE = ROOT / "scripts/lsp-workspace-contract/workspace.py"
HEADING = re.compile(
    r"^## 9\. ([0-9]+) 例 × ([0-9]+) mutant 行为合同$",
    re.MULTILINE,
)


class CheckFailure(RuntimeError):
    pass


def heading_counts(text):
    matches = list(HEADING.finditer(text))
    if len(matches) != 1:
        raise CheckFailure(
            "docs/lsp-workspace-design.md must contain exactly one machine-readable "
            "section 9 count heading"
        )
    match = matches[0]
    return int(match.group(1)), int(match.group(2))


def mutant_roster(text):
    """Read the behavioral roster, not every mutation mutate.py can spell.

    A mutant only counts after run.sh compiles it and runs its owning case, so
    top-level, one-line expect_mutant_red calls are the single source of truth.
    The observe identity and an uncalled mutate.py branch are not negative
    controls and therefore cannot silently inflate the documented count.
    """
    names = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("expect_mutant_red "):
            continue
        try:
            fields = shlex.split(line, comments=True, posix=True)
        except ValueError as error:
            raise CheckFailure(f"run.sh:{line_number}: invalid mutant call: {error}") from error
        if len(fields) != 4:
            raise CheckFailure(
                f"run.sh:{line_number}: expect_mutant_red must stay one line with three arguments"
            )
        names.append(fields[1])
    if len(names) != len(set(names)):
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        raise CheckFailure(f"run.sh repeats mutant(s): {', '.join(duplicates)}")
    return names


def case_roster(text):
    try:
        tree = ast.parse(text, filename=str(WORKSPACE))
    except SyntaxError as error:
        raise CheckFailure(f"workspace.py does not parse: {error}") from error
    values = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "CASES" for target in node.targets):
            values.append(node.value)
    if len(values) != 1 or not isinstance(values[0], ast.Dict):
        raise CheckFailure("workspace.py must define CASES exactly once as a dictionary literal")
    names = []
    for key in values[0].keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise CheckFailure("workspace.py CASES keys must be string literals")
        names.append(key.value)
    if len(names) != len(set(names)):
        raise CheckFailure("workspace.py CASES contains a duplicate case name")
    return names


def check(design_text, run_text, workspace_text):
    documented_cases, documented_mutants = heading_counts(design_text)
    cases = case_roster(workspace_text)
    mutants = mutant_roster(run_text)
    problems = []
    if documented_cases != len(cases):
        problems.append(
            f"design documents {documented_cases} cases, but workspace.py CASES has {len(cases)}"
        )
    if documented_mutants != len(mutants):
        problems.append(
            f"design documents {documented_mutants} mutants, but run.sh executes {len(mutants)}"
        )
    if problems:
        raise CheckFailure("; ".join(problems))
    return len(cases), len(mutants)


def changed_heading(text, cases, mutants):
    match = HEADING.search(text)
    if match is None:
        raise CheckFailure("self-test could not find the section 9 count heading")
    replacement = f"## 9. {cases} 例 × {mutants} mutant 行为合同"
    return text[:match.start()] + replacement + text[match.end():]


def reject_count_mutation(kind, design_text, run_text, workspace_text, cases, mutants):
    changed_cases = cases + 1 if kind == "case" else cases
    changed_mutants = mutants + 1 if kind == "mutant" else mutants
    mutant = changed_heading(design_text, changed_cases, changed_mutants)
    try:
        check(mutant, run_text, workspace_text)
    except CheckFailure as error:
        changed = changed_cases if kind == "case" else changed_mutants
        expected = f"design documents {changed} {kind}s"
        if expected not in str(error):
            raise CheckFailure(
                f"{kind}-count negative control failed for the wrong reason: {error}"
            )
        print(f"PASS  {kind}-count negative control turns the roster check red")
        return
    raise CheckFailure(f"{kind}-count negative control stayed green")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    design_text = DESIGN.read_text(encoding="utf-8")
    run_text = RUNNER.read_text(encoding="utf-8")
    workspace_text = WORKSPACE.read_text(encoding="utf-8")
    try:
        cases, mutants = check(design_text, run_text, workspace_text)
        print(f"PASS  LSP workspace design roster matches {cases} cases × {mutants} mutants")
        if args.self_test:
            reject_count_mutation(
                "case", design_text, run_text, workspace_text, cases, mutants
            )
            reject_count_mutation(
                "mutant", design_text, run_text, workspace_text, cases, mutants
            )
    except (CheckFailure, OSError) as error:
        print(f"lsp-workspace roster check: FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
