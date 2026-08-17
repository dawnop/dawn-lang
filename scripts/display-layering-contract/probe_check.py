#!/usr/bin/env python3
"""Partition the Display probe's output into the three named assertions.

The probe prints one `<label>\tvalue` line per observation and `probe.expect`
holds the hand-written answers. This script is the only place that says which
label belongs to which assertion, so a mutant's red set names a rule rather
than a diff.

Usage:
    probe_check.py <assertion> <expect-file> <observed-file>
    probe_check.py --labels
    probe_check.py --self-test
"""

from pathlib import Path
import sys


# Which observation answers which rule. Every label in probe.expect must appear
# in exactly one group, and `validate_groups` holds that: a label that drifts
# out of the probe, or a new one nobody classified, fails the harness instead of
# being silently unchecked.
GROUPS = {
    # A Display impl decides the top-level rendering, in place of whatever Show
    # the value would otherwise have gone through: the one it inherits from an
    # opaque target (Char over Int), one the type wrote itself (Tag), and the
    # String identity (Inner over String).
    "display_wins_over_show": ("top-char", "top-tag", "layer1"),
    # And the question is asked again at every peel layer of an opaque stack,
    # rather than once on the type as written.
    "display_is_asked_at_every_peel_layer": ("layer2", "layer3"),
    # The control: Display is the top-level rendering and touches nothing else.
    # A value inside a structure still renders through Show, and a value behind
    # a `[T: Show]` bound still renders through its witness.
    "show_stays_the_nested_rendering": (
        "nested-list",
        "nested-tag",
        "nested-inner",
        "nested-tuple",
        "bound-char",
        "bound-inner",
        "list-map",
    ),
}


class ProbeError(ValueError):
    pass


def parse(text: str, what: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if "\t" not in line:
            raise ProbeError(f"{what} line {number}: no tab separator: {line!r}")
        label, value = line.split("\t", 1)
        if not label:
            raise ProbeError(f"{what} line {number}: empty label")
        if label in out:
            raise ProbeError(f"{what} line {number}: duplicate label {label!r}")
        out[label] = value
    if not out:
        raise ProbeError(f"{what}: no observations")
    return out


def validate_groups(expected: dict[str, str]) -> None:
    classified: set[str] = set()
    for assertion, labels in GROUPS.items():
        for label in labels:
            if label in classified:
                raise ProbeError(f"label {label!r} is in two assertions")
            classified.add(label)
        if not labels:
            raise ProbeError(f"assertion {assertion!r} covers no label")
    missing = classified - expected.keys()
    if missing:
        raise ProbeError(
            "assertions name label(s) the probe does not print: "
            + ", ".join(sorted(missing))
        )
    unclassified = expected.keys() - classified
    if unclassified:
        raise ProbeError(
            "probe prints label(s) no assertion covers: "
            + ", ".join(sorted(unclassified))
        )


def check(assertion: str, expected: dict[str, str], observed: dict[str, str]) -> None:
    if assertion not in GROUPS:
        raise ProbeError(f"unknown assertion: {assertion}")
    for label in GROUPS[assertion]:
        want = expected[label]
        if label not in observed:
            raise ProbeError(f"{assertion}: {label} was not printed")
        got = observed[label]
        if got != want:
            raise ProbeError(f"{assertion}: {label} is {got!r}, expected {want!r}")


BASE_EXPECT = (
    "top-char\ta\n"
    "top-tag\t[redacted]\n"
    "layer1\t<inner>\n"
    "layer2\t<inner>\n"
    "layer3\t<inner>\n"
    "nested-list\t[97, 98]\n"
    "nested-tag\t[***]\n"
    "nested-inner\t[\"x\"]\n"
    "nested-tuple\t(97, ***)\n"
    "bound-char\t97\n"
    "bound-inner\t\"x\"\n"
    "list-map\t[\"a\", \"b\"]\n"
)


def self_test() -> None:
    expected = parse(BASE_EXPECT, "expect")
    validate_groups(expected)
    for assertion in GROUPS:
        check(assertion, expected, expected)

    refused = 0

    def must_refuse(name: str, thunk) -> None:
        nonlocal refused
        try:
            thunk()
        except ProbeError:
            refused += 1
            return
        raise AssertionError(f"probe self-test mutant stayed green: {name}")

    # every observation is load-bearing: perturbing any single one reds exactly
    # the assertion that claims it, and no assertion may be vacuous
    for assertion, labels in GROUPS.items():
        for label in labels:
            broken = dict(expected)
            broken[label] = broken[label] + "!"
            must_refuse(
                f"{label} moved but {assertion} stayed green",
                lambda a=assertion, b=broken: check(a, expected, b),
            )
            dropped = {k: v for k, v in expected.items() if k != label}
            must_refuse(
                f"{label} vanished but {assertion} stayed green",
                lambda a=assertion, d=dropped: check(a, expected, d),
            )
            for other in GROUPS:
                if other == assertion:
                    continue
                broken2 = dict(expected)
                broken2[label] = broken2[label] + "!"
                try:
                    check(other, expected, broken2)
                except ProbeError as error:
                    raise AssertionError(
                        f"{label} belongs to {assertion} but reddened {other}: {error}"
                    ) from error

    must_refuse("an unclassified label passed validation", lambda: validate_groups(
        parse(BASE_EXPECT + "surprise\t1\n", "expect")
    ))
    must_refuse("a missing label passed validation", lambda: validate_groups(
        parse(BASE_EXPECT.replace("layer3\t<inner>\n", ""), "expect")
    ))
    must_refuse("a line without a tab parsed", lambda: parse("nope\n", "expect"))
    must_refuse("a duplicate label parsed", lambda: parse("a\t1\na\t2\n", "expect"))
    must_refuse("empty output parsed", lambda: parse("", "expect"))
    must_refuse("an unknown assertion was accepted", lambda: check(
        "no_such_assertion", expected, expected
    ))
    print(f"probe self-test: {refused} mutant(s) refused")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if sys.argv[1:] == ["--labels"]:
        for assertion in GROUPS:
            print(assertion)
        return
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: probe_check.py [--self-test | --labels | "
            "<assertion> <expect> <observed>]"
        )
    assertion, expect_path, observed_path = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        expected = parse(Path(expect_path).read_text(encoding="utf-8"), "expect")
        validate_groups(expected)
        observed = parse(Path(observed_path).read_text(encoding="utf-8"), "observed")
        check(assertion, expected, observed)
    except ProbeError as error:
        raise SystemExit(f"{error}") from error


if __name__ == "__main__":
    main()
