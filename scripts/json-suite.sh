#!/usr/bin/env bash
# JSONTestSuite as a gate, not as a claim.
#
# README has said "过 JSONTestSuite 全部 318 例" since M4, and the 318 fixture
# files have been tracked ever since — but nothing re-ran them. A number obtained
# once by hand is not a gate: while it stood, the renderer learned to emit a raw
# 0x08 for a parsed `\b`, integers above 2^53 were silently rounded, and every
# suite in the repo stayed green. This script is that claim made checkable.
#
# The harness itself is Dawn (examples/projects/json/src/suite.dawn) and reads the
# fixture directory in one process. A shell loop over `dawn run` would be 318 JVM
# starts — minutes, which is how a check ends up not running on every push.
#
# Verdicts: y_ must be accepted (and must survive parse→render→parse unchanged),
# n_ must be rejected, i_ is implementation-defined and only counted. A nonzero
# exit means a mandatory case moved.
set -euo pipefail
cd "$(dirname "$0")/.."

DAWN=${DAWN_BIN:-./bin/dawn}

"$DAWN" test packages/json
"$DAWN" test examples/projects/json
"$DAWN" run examples/projects/json --suite examples/projects/json/suite/test_parsing
