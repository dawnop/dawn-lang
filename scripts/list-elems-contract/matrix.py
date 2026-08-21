#!/usr/bin/env python3
"""The mutant-matrix checker, borrowed from the gate that first wrote it.

`scripts/pipe-contract/matrix.py` carries no pipe in it: it parses
`role`/`owner`/`red` lines, enforces the three ownership rules, diffs an
observation against a record, and perturbs a synthetic record once per rule so
that the checker has been seen failing. All of that is this contract's
requirement too, unchanged.

So this is a loader, not a fourth copy. Three copies of the same `--selftest`
already exist in `scripts/` for the single-mutant gates, and a selftest that
rots in one copy is precisely the failure this family of gates was built to
prevent -- the copy nobody re-ran is indistinguishable from the copy that
cannot fail. Loading it also makes the dependency visible to the gate map,
which scrapes the path below out of this file.

If that file moves, this import raises and the gate goes red by name. That is
the intended failure: a silent fallback would be a gate testing nothing.

    matrix.py --validate matrix.txt
    matrix.py --check observed.txt matrix.txt
    matrix.py --record observed.txt matrix.txt
    matrix.py --selftest
"""

import importlib.util
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "scripts/pipe-contract/matrix.py"

if not SOURCE.is_file():
    raise SystemExit(f"list-elems-contract: {SOURCE} is gone; the matrix checker has moved")

_spec = importlib.util.spec_from_file_location("_pipe_contract_matrix", SOURCE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

if __name__ == "__main__":
    sys.exit(_module.main())
