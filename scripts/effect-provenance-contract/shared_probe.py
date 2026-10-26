"""Execute the frozen shared-hot-function fixture with observation enabled.

The timed entry and six workloads are copied without edits. This separate
entry checks the retained observation root without timing or changing it.
"""
import hashlib
from run import HERE, exact


def shared_probe(run):
    project = run.out/'shared_probe'
    (project/'src').mkdir(parents=True, exist_ok=True)
    kernel = HERE/'u1-shared/kernels.dawn'
    (project/'src/kernels.dawn').write_bytes(kernel.read_bytes())
    (project/'dawn.toml').write_text('schema = 1\nname = "shared_probe"\n')
    (project/'src/main.dawn').write_text('use std/io.{println}\nuse kernels.{observation_probe}\n'
        'pub fn main() -> Unit !io = println("${observation_probe()}")\n')
    # Two exact linear-congruential steps, computed independently of the log.
    value = 3
    for _ in range(2):
        value = (value*1664525+1013904223) & ((1 << 64)-1)
        if value >= 1 << 63:
            value -= 1 << 64
    run.execute('shared-hot-observed-probe', project, exact(str(value)+'\n'))
    assert (project/'src/kernels.dawn').read_bytes() == kernel.read_bytes()
    (run.out/'shared-probe-input.sha256').write_text(hashlib.sha256(kernel.read_bytes()).hexdigest()+'\n')
