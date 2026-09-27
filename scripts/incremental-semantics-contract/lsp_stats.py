"""Decode the private observer schema without confusing absence with zero work."""

FIELDS = (
    "reused_modules", "checked_modules", "comptime_modules", "retained_modules",
    "retained_text_units",
)


def decode(line):
    cells = line.split("\t")
    if len(cells) < 3 or cells[0] != "LSP_BODY_STATS" or cells[1] not in {"project", "standalone"}:
        raise ValueError("invalid analysis trace header")
    if cells[2:] == ["unobserved"]:
        return {"scope": cells[1], "observed": False, "counts": None}
    if len(cells[2:]) != len(FIELDS) or any(not cell.isascii() or not cell.isdecimal() for cell in cells[2:]):
        raise ValueError("invalid analysis trace counters")
    return {"scope": cells[1], "observed": True, "counts": dict(zip(FIELDS, map(int, cells[2:])))}
