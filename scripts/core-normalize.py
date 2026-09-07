#!/usr/bin/env python3
"""Conservative Core noise classification; exact goldens remain authoritative.

Only generated-name $Adt IDs are alpha-renamed, consistently within a module.
Quoted text is opaque, including compiler-generated panic messages: this dump
does not distinguish them from user strings. Trait IDs stay exact until the
dump supplies enough identity information to normalize them safely.
"""
import re
import sys
import tempfile
from pathlib import Path

PART = re.compile(r'"(?:\\.|[^"\\])*"|(?<=\$)Adt[0-9]+\b')


def normalize(text):
    names = {}

    def replace(match):
        token = match.group()
        if token.startswith('"'):
            return token
        return names.setdefault(token, f"AdtN{len(names)}")

    return PART.sub(replace, text)


def equal_directories(left, right):
    old = {p.name: normalize(p.read_text()) for p in Path(left).glob("*.core")}
    new = {p.name: normalize(p.read_text()) for p in Path(right).glob("*.core")}
    return bool(old) and old == new


def selftest():
    assert normalize('call m.eq$Adt123\ncall m.eq$Adt123\n') == normalize('call m.eq$Adt456\ncall m.eq$Adt456\n')
    assert normalize('call m.eq$Adt123\ncall m.eq$Adt123\n') != normalize('call m.eq$Adt456\ncall m.eq$Adt789\n')
    for a, b in [
        ('str "Adt123"', 'str "Adt456"'),
        ('str "eq$Adt123"', 'str "eq$Adt456"'),
        ('str "escaped \\" eq$Adt123"', 'str "escaped \\" eq$Adt456"'),
        ('str "unwrapped None at file.dawn:12"', 'str "unwrapped None at file.dawn:13"'),
        ('str "at embedded.dawn:12\\nsource"', 'str "at embedded.dawn:13\\nsource"'),
        ('ctor Adt123/Adt123', 'ctor Adt456/Adt456'),
        ('call method trait=123 x slot=0', 'call method trait=456 x slot=0'),
    ]:
        assert normalize(a) != normalize(b), (a, b)
    assert normalize('str "eq$Adt123"\ncall m.eq$Adt456') == 'str "eq$Adt123"\ncall m.eq$AdtN0'
    with tempfile.TemporaryDirectory(prefix="core-normalize-test-") as tmp:
        left, right = Path(tmp) / "old", Path(tmp) / "new"
        left.mkdir()
        right.mkdir()
        (left / "m.core").write_text('fn m.eq$Adt123\ncall m.eq$Adt123\n')
        (right / "m.core").write_text('fn m.eq$Adt456\ncall m.eq$Adt456\n')
        assert equal_directories(left, right)
        (right / "m.core").write_text('fn m.eq$Adt123\ncall m.eq$Adt456\n')
        assert not equal_directories(left, right)
        (right / "m.core").write_text((left / "m.core").read_text())
        (right / "extra.core").write_text('module extra\n')
        assert not equal_directories(left, right)
    print("OK: Core normalization preserves literals and identity relationships")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        selftest()
    elif len(sys.argv) == 4 and sys.argv[1] == "--equal":
        sys.exit(0 if equal_directories(*sys.argv[2:]) else 1)
    else:
        sys.stdout.write(normalize(sys.stdin.read()))
