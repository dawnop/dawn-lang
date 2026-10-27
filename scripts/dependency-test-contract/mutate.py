#!/usr/bin/env python3
"""Restore dependency tests at the shared product boundary for the red control.

The compiler must still build; the product and diagnostic oracles own failure.
"""
from pathlib import Path
import sys


def main():
    name, root = sys.argv[1], Path(sys.argv[2])
    assert name == 'retain-dependency-tests'
    path = root / 'selfhost/src/driver/analyze.dawn'
    text = path.read_text()
    old = 'analyze_observed(loaded, std, opts, js, None, false)'
    assert text.count(old) == 1, (name, text.count(old))
    path.write_text(text.replace(old, 'analyze_observed(loaded, std, opts, js, None, true)'))


if __name__ == '__main__':
    main()
