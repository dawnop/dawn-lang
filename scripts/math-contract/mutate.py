#!/usr/bin/env python3
"""Exactly-once source mutations owned by the math accuracy contract.

The preflight exercises these anchors before builds. Controls must compile,
exit normally, reach the completion marker and fail their named oracle rows.
"""
from pathlib import Path
import sys

MUTATIONS = {
    'exp-term': (('std/math.dawn',
        'const FD_E_EXP_P5: Float = float_of_bits(0x3e66376972bea4d0)',
        'const FD_E_EXP_P5: Float = 0.0'),),
    'reduction-split': (('std/math.dawn',
        'const FD_K_REM_PIO2_PIO2: List[Float] = [float_of_bits(0x3ff921fb40000000)',
        'const FD_K_REM_PIO2_PIO2: List[Float] = [float_of_bits(0x3ff921fb50000000)'),),
    'round-half': (('std/math.dawn',
        '''pub fn round(x: Float) -> Float = {
  let t = trunc(x)
  let d = x - t
  if d >= 0.5 { t + 1.0 } else if d <= -0.5 { t - 1.0 } else { t }
}''',
        'pub fn round(x: Float) -> Float = floor(x + 0.5)'),),
}


def main():
    name, root = sys.argv[1], Path(sys.argv[2])
    for rel, old, new in MUTATIONS[name]:
        p = root / rel
        text = p.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f'{name}: anchor in {rel} is not unique ({count} matches)')
        p.write_text(text.replace(old,new))

if __name__=='__main__':main()
