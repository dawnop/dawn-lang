#!/usr/bin/env python3
"""Hold the SYN-05 mutants to a recorded red set, and to the ownership property.

`run.sh` used to assert only that mutant X reddens assertion A. That records
ownership in prose and enforces nothing: if a later change makes a second
mutant redden A as well, A is owned by neither and nothing goes red. The
measurement that chose the owners has to be the gate, not a thing that happened
once.

So every mutant is run against the *whole* assertion set and its red set is
compared with `matrix.txt`. Some overlaps are by design and are recorded rather
than forbidden: a module-qualified call is an `EMethod`, so `drop-method-prepend`
reddens `qualified` too. What may not overlap is an *owner*.

Three rules, all machine-checked against the record:

  1. every counted mutant has an owner, and that owner is in its own red set;
  2. no other counted mutant reddens it, which is what "owns" means;
  3. the observed red set equals the recorded one, in both directions.

Rule 3 catches an owner that stops going red and a collision that appears where
the record says there was none. Rules 1 and 2 read the record alone, so every
shard checks the whole ownership structure even though it builds a third of the
mutants.

`--selftest` perturbs a known-good record once per rule: a checker whose red has
never been observed is a checker nobody can rely on.

    matrix.py --validate matrix.txt
    matrix.py --check observed.txt matrix.txt
    matrix.py --record observed.txt matrix.txt
    matrix.py --selftest

`--record` rewrites the red sets and nothing else. Which assertion *owns* a
mutant is a design decision, so it stays a hand edit: a recorder that could
reassign owners would launder a collision into the record it is supposed to
catch.
"""

import sys

ROLES = ("counted", "recorded")


def parse(text, name):
    """-> (roles, owners, reds). Raises SystemExit on a malformed record."""
    roles, owners, reds = {}, {}, {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise SystemExit(f"{name}:{n}: expected `<kind> <mutant> <value>`, got: {raw}")
        kind, mutant, value = parts
        if kind == "role":
            if value not in ROLES:
                raise SystemExit(f"{name}:{n}: role must be one of {ROLES}, got `{value}`")
            roles[mutant] = value
        elif kind == "owner":
            if mutant in owners:
                raise SystemExit(f"{name}:{n}: `{mutant}` already has an owner")
            owners[mutant] = value
        elif kind == "red":
            reds.setdefault(mutant, set()).add(value)
        else:
            raise SystemExit(f"{name}:{n}: unknown kind `{kind}`")
    for mutant in set(owners) | set(reds):
        roles.setdefault(mutant, "counted")
        reds.setdefault(mutant, set())
    return roles, owners, reds


def validate(roles, owners, reds):
    """The ownership structure, read out of the record alone."""
    problems = []
    counted = [m for m in sorted(roles) if roles[m] == "counted"]

    for mutant in counted:
        owner = owners.get(mutant)
        if owner is None:
            problems.append(f"{mutant}: counted but has no owning assertion")
            continue
        # rule 1: a mutant its owner does not redden proves nothing about it
        if owner not in reds[mutant]:
            problems.append(
                f"{mutant}: its owner `{owner}` is not in its red set"
            )
        # rule 2: and an assertion two mutants can redden is owned by neither
        others = [m for m in counted if m != mutant and owner in reds[m]]
        if others:
            problems.append(
                f"{mutant}: its owner `{owner}` is also reddened by "
                + ", ".join(others)
            )

    for mutant in sorted(roles):
        if roles[mutant] == "recorded" and mutant in owners:
            problems.append(
                f"{mutant}: recorded rather than counted, so it may not own an assertion"
            )
    return problems


def compare(observed, recorded, obs_name, rec_name):
    """Rule 3, restricted to the mutants the observation actually covers."""
    _, _, obs_reds = observed
    _, _, rec_reds = recorded
    problems = []
    for mutant in sorted(obs_reds):
        if mutant not in rec_reds:
            problems.append(f"{mutant}: ran, but {rec_name} has no record of it")
            continue
        new = sorted(obs_reds[mutant] - rec_reds[mutant])
        gone = sorted(rec_reds[mutant] - obs_reds[mutant])
        for a in new:
            problems.append(f"{mutant}: newly reddens `{a}`, which {rec_name} does not record")
        for a in gone:
            problems.append(f"{mutant}: no longer reddens `{a}`, which {rec_name} records")
    return problems


GOOD = """
# two mutants, one assertion each, plus a control that reddens everything
role  alpha            counted
owner alpha            a_owner
red   alpha            a_owner
red   alpha            shared
role  beta             counted
owner beta             b_owner
red   beta             b_owner
red   beta             shared
role  control          recorded
red   control          a_owner
red   control          b_owner
"""


def selftest():
    mutants = [
        (
            "an owner that the mutant does not redden",
            GOOD.replace("red   alpha            a_owner\n", ""),
            "validate",
        ),
        (
            "an owner two counted mutants redden",
            GOOD.replace("owner beta             b_owner", "owner beta             a_owner"),
            "validate",
        ),
        (
            "a counted mutant with no owner",
            GOOD.replace("owner alpha            a_owner\n", ""),
            "validate",
        ),
        (
            "a recorded-not-counted mutant that claims an owner",
            GOOD.replace("role  control          recorded",
                         "role  control          recorded\nowner control          shared"),
            "validate",
        ),
    ]
    drifts = [
        (
            "an observation whose owner stopped going red",
            GOOD.replace("red   alpha            a_owner\n", ""),
        ),
        (
            "an observation with a collision the record does not have",
            GOOD.replace("red   beta             shared",
                         "red   beta             shared\nred   beta             a_owner"),
        ),
    ]

    failures = []
    good = parse(GOOD, "good")
    if validate(*good):
        failures.append("the unmutated record was refused: " + "; ".join(validate(*good)))
    if compare(good, good, "good", "good"):
        failures.append("the unmutated record disagreed with itself")

    for label, text, _ in mutants:
        if not validate(*parse(text, "mutant")):
            failures.append(f"mutant not caught: {label}")
        else:
            print(f"  refused: {label}")
    for label, text in drifts:
        if not compare(parse(text, "observed"), good, "observed", "record"):
            failures.append(f"drift not caught: {label}")
        else:
            print(f"  refused: {label}")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print(f"selftest: {len(mutants) + len(drifts)} perturbation(s) refused, "
          "clean record accepted")
    return 0


def read(path):
    with open(path, encoding="utf-8") as handle:
        return parse(handle.read(), path)


def rewrite(observed_path, record_path):
    """Replace the record's red sets with the observation, keeping the rest."""
    with open(record_path, encoding="utf-8") as handle:
        old = handle.read()
    header = []
    for raw in old.splitlines():
        if raw.startswith("#") or not raw.strip():
            header.append(raw)
        else:
            break
    while header and not header[-1].strip():
        header.pop()

    roles, owners, _ = parse(old, record_path)
    _, _, new_reds = read(observed_path)
    missing = sorted(set(roles) - set(new_reds))
    if missing:
        raise SystemExit(
            "--record needs every mutant in one run; missing: " + ", ".join(missing)
        )

    lines = list(header) + [""]
    for mutant in sorted(roles):
        lines.append(f"role\t{mutant}\t{roles[mutant]}")
        if mutant in owners:
            lines.append(f"owner\t{mutant}\t{owners[mutant]}")
        for assertion in sorted(new_reds[mutant]):
            lines.append(f"red\t{mutant}\t{assertion}")
        lines.append("")
    with open(record_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip("\n") + "\n")
    print(f"recorded {record_path}")


def main():
    args = sys.argv[1:]
    if args[:1] == ["--selftest"]:
        return selftest()

    if args[:1] == ["--record"] and len(args) == 3:
        rewrite(args[1], args[2])
        return 0

    if args[:1] == ["--validate"] and len(args) == 2:
        problems = validate(*read(args[1]))
        label = f"{args[1]}: ownership structure"
    elif args[:1] == ["--check"] and len(args) == 3:
        observed, recorded = read(args[1]), read(args[2])
        problems = validate(*recorded) + compare(observed, recorded, args[1], args[2])
        label = f"{args[1]}: red sets and ownership structure"
    else:
        raise SystemExit(__doc__.strip().splitlines()[-3].strip())

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"OK   {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
