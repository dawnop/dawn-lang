#!/usr/bin/env python3
"""Keep every Display-layering matrix field executable and fail closed.

matrix.txt is the harness's expectation about its own mutants, so a field nobody
reads is a field that can lie. Every record below is consumed by run.sh, and the
self-test perturbs each one to prove the validator would catch it.
"""

from pathlib import Path
import sys


MUTATIONS = ("drop-display-question", "ask-display-once")
WINS = "display_wins_over_show"
LAYERS = "display_is_asked_at_every_peel_layer"
CONTROL = "show_stays_the_nested_rendering"

OWNERS = {
    "drop-display-question": WINS,
    "ask-display-once": LAYERS,
}
REDS = {
    "drop-display-question": (WINS, LAYERS),
    "ask-display-once": (LAYERS,),
}

BASE = """role\tdrop-display-question\tcounted
role\task-display-once\tcounted
owner\tdrop-display-question\tdisplay_wins_over_show
owner\task-display-once\tdisplay_is_asked_at_every_peel_layer
red\tdrop-display-question\tdisplay_wins_over_show
red\tdrop-display-question\tdisplay_is_asked_at_every_peel_layer
red\task-display-once\tdisplay_is_asked_at_every_peel_layer
control\tshow_stays_the_nested_rendering
"""


class MatrixError(ValueError):
    pass


def validate(text: str) -> None:
    roles: dict[str, str] = {}
    owners: dict[str, str] = {}
    reds: set[tuple[str, str]] = set()
    controls: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        record = fields[0]
        if record == "role":
            if len(fields) != 3:
                raise MatrixError(f"line {number}: role takes two fields")
            mutation, kind = fields[1], fields[2]
            if mutation not in MUTATIONS:
                raise MatrixError(f"line {number}: unknown mutation {mutation!r}")
            if mutation in roles:
                raise MatrixError(f"line {number}: duplicate role for {mutation}")
            if kind != "counted":
                raise MatrixError(f"line {number}: role kind is {kind!r}, not 'counted'")
            roles[mutation] = kind
        elif record == "owner":
            if len(fields) != 3:
                raise MatrixError(f"line {number}: owner takes two fields")
            mutation, assertion = fields[1], fields[2]
            if mutation not in MUTATIONS:
                raise MatrixError(f"line {number}: unknown mutation {mutation!r}")
            if mutation in owners:
                raise MatrixError(f"line {number}: duplicate owner for {mutation}")
            if assertion != OWNERS[mutation]:
                raise MatrixError(
                    f"line {number}: {mutation} owns {assertion!r}, "
                    f"expected {OWNERS[mutation]!r}"
                )
            owners[mutation] = assertion
        elif record == "red":
            if len(fields) != 3:
                raise MatrixError(f"line {number}: red takes two fields")
            mutation, assertion = fields[1], fields[2]
            if mutation not in MUTATIONS:
                raise MatrixError(f"line {number}: unknown mutation {mutation!r}")
            if (mutation, assertion) in reds:
                raise MatrixError(f"line {number}: duplicate red {mutation}/{assertion}")
            reds.add((mutation, assertion))
        elif record == "control":
            if len(fields) != 2:
                raise MatrixError(f"line {number}: control takes one field")
            if controls:
                raise MatrixError(f"line {number}: duplicate control record")
            if fields[1] != CONTROL:
                raise MatrixError(
                    f"line {number}: control is {fields[1]!r}, expected {CONTROL!r}"
                )
            controls.append(fields[1])
        else:
            raise MatrixError(f"line {number}: unknown record {record!r}")

    for mutation in MUTATIONS:
        if mutation not in roles:
            raise MatrixError(f"missing role record for {mutation}")
        if mutation not in owners:
            raise MatrixError(f"missing owner record for {mutation}")
        want = {(mutation, a) for a in REDS[mutation]}
        have = {r for r in reds if r[0] == mutation}
        if have != want:
            raise MatrixError(
                f"{mutation} red set is {sorted(a for _, a in have)}, "
                f"expected {sorted(a for _, a in want)}"
            )
    if not controls:
        raise MatrixError("missing control record")
    for mutation, assertion in reds:
        if assertion == CONTROL:
            raise MatrixError(f"{mutation} is recorded as reddening the control")

    # Two mutants with the same red set are one piece of evidence written twice:
    # neither says which rule it broke.
    sets = {m: frozenset(a for mm, a in reds if mm == m) for m in MUTATIONS}
    for i, left in enumerate(MUTATIONS):
        for right in MUTATIONS[i + 1:]:
            if sets[left] == sets[right]:
                raise MatrixError(f"{left} and {right} have the same red set")

    # A mutant owns the assertion it reddens *most specifically*: among the
    # mutants that redden an assertion, the one with the smallest red set is the
    # one whose evidence is about that rule and not about a wider break. A tie
    # would leave the attribution unwritten, so it is an error.
    for mutation, assertion in owners.items():
        if (mutation, assertion) not in reds:
            raise MatrixError(f"{mutation} does not redden the assertion it owns")
        rivals = [m for m in MUTATIONS if (m, assertion) in reds]
        best = min(len(sets[m]) for m in rivals)
        narrowest = [m for m in rivals if len(sets[m]) == best]
        if len(narrowest) != 1:
            raise MatrixError(
                f"{assertion} has no single narrowest mutant: "
                + ", ".join(sorted(narrowest))
            )
        if narrowest[0] != mutation:
            raise MatrixError(
                f"{assertion} is owned by {mutation}, but {narrowest[0]} reddens it "
                "more specifically"
            )
    if len(set(owners.values())) != len(owners):
        raise MatrixError("two mutants own the same assertion")
    uncovered = ({WINS, LAYERS}) - {a for _, a in reds}
    if uncovered:
        raise MatrixError(
            "assertion(s) no mutant reddens: " + ", ".join(sorted(uncovered))
        )


def replaced(old: str, new: str) -> str:
    if BASE.count(old) != 1:
        raise AssertionError(f"self-test anchor is not unique: {old!r}")
    return BASE.replace(old, new)


def self_test() -> None:
    validate(BASE)
    mutants = {
        "role mutation lies": replaced(
            "role\tdrop-display-question\tcounted",
            "role\tno-such-mutant\tcounted",
        ),
        "role kind lies": replaced(
            "role\task-display-once\tcounted",
            "role\task-display-once\trecorded",
        ),
        "owner assertion lies": replaced(
            "owner\task-display-once\tdisplay_is_asked_at_every_peel_layer",
            "owner\task-display-once\tdisplay_wins_over_show",
        ),
        "owner is claimed by both mutants": replaced(
            "red\task-display-once\tdisplay_is_asked_at_every_peel_layer",
            "red\task-display-once\tdisplay_wins_over_show",
        ),
        "a red row is dropped": replaced(
            "red\tdrop-display-question\tdisplay_is_asked_at_every_peel_layer\n", ""
        ),
        "a red row is invented": BASE + f"red\task-display-once\t{WINS}\n",
        # the wider mutant claiming the assertion the narrower one reddens
        "owners are swapped": replaced(
            f"owner\tdrop-display-question\t{WINS}\n"
            f"owner\task-display-once\t{LAYERS}\n",
            f"owner\tdrop-display-question\t{LAYERS}\n"
            f"owner\task-display-once\t{WINS}\n",
        ),
        "the control is recorded red": BASE + f"red\task-display-once\t{CONTROL}\n",
        "control lies": replaced(
            f"control\t{CONTROL}", "control\tdisplay_wins_over_show"
        ),
        "control is duplicated": BASE + f"control\t{CONTROL}\n",
        "control is missing": replaced(f"control\t{CONTROL}\n", ""),
        "role is missing": replaced("role\task-display-once\tcounted\n", ""),
        "role is duplicated": BASE + "role\task-display-once\tcounted\n",
        "owner is missing": replaced(
            "owner\tdrop-display-question\tdisplay_wins_over_show\n", ""
        ),
        "owner is duplicated": BASE + (
            "owner\tdrop-display-question\tdisplay_wins_over_show\n"
        ),
        "red is duplicated": BASE + f"red\task-display-once\t{LAYERS}\n",
        "record is unknown": BASE + "note\tnot-a-contract-record\n",
        "role field count is wrong": replaced(
            "role\task-display-once\tcounted", "role\task-display-once"
        ),
        "control field count is wrong": replaced(
            f"control\t{CONTROL}", f"control\t{CONTROL}\textra"
        ),
    }
    for name, mutant in mutants.items():
        try:
            validate(mutant)
        except MatrixError:
            continue
        raise AssertionError(f"matrix self-test mutant stayed green: {name}")
    print(f"matrix self-test: {len(mutants)} mutant(s) refused")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if len(sys.argv) != 2:
        raise SystemExit("usage: matrix_check.py [--self-test | matrix.txt]")
    try:
        validate(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except MatrixError as error:
        raise SystemExit(f"invalid display-layering matrix: {error}") from error


if __name__ == "__main__":
    main()
