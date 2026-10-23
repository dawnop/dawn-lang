#!/usr/bin/env python3
"""Delete after knife 4. Compile real regressions before trusting the contract."""
from pathlib import Path
import sys

MUTATIONS = {
    "label-as-assignment": (
        "selfhost/src/front/parser.dawn",
        ((
            "      args = args ++ [Arg { name: Some(arg_name.text), e: value, trailing: false, lo: arg_name.lo, hi: e_hi(value) }]",
            """      if kind_ahead(p, st1, 1) == EQ {
        args = args ++ [pos_arg(EBlock([SAssign(arg_name.text, value, arg_name.lo, arg_name.hi, arg_name.lo, e_hi(value))], None, arg_name.lo, e_hi(value)))]
      } else {
        args = args ++ [Arg { name: Some(arg_name.text), e: value, trailing: false, lo: arg_name.lo, hi: e_hi(value) }]
      }""",
        ),),
    ),
    "formatter-rewrites-separator": (
        "selfhost/src/front/fmt.dawn",
        ((
            "  Ok(reflow(cps, stream, marks, block_arrow(cps, raw)))",
            '  Ok(str.replace(reflow(cps, stream, marks, block_arrow(cps, raw)), " = ", ": "))',
        ),),
    ),
    "migrator-rewrites-type": (
        "scripts/named-arg-migrate/migrate.py",
        ((
            '    for offset in sorted({hit["offset"] for hit in hits}, reverse=True):',
            '    hits = hits + [{"offset": source.index("x: Int") + 1}]\n' +
            '    for offset in sorted({hit["offset"] for hit in hits}, reverse=True):',
        ),),
    ),
}


def main():
    if sys.argv[1:] == ["--list"]:
        print("\n".join(MUTATIONS))
        return
    name, root = sys.argv[1:]
    relative, replacements = MUTATIONS[name]
    path = Path(root) / relative
    text = path.read_text()
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{name}: expected exactly one match, found {count}")
        text = text.replace(old, new)
    path.write_text(text)
    print(relative)


if __name__ == "__main__":
    main()
