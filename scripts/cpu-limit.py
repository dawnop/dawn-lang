#!/usr/bin/env python3
"""Give a correctness oracle CPU time without charging scheduler waits.

The kernel accounts every thread, and children inherit the per-process limit.
The enclosing gate job still owns the wall watchdog for blocked I/O. This is
an execution allowance, not a benchmark or a replacement for output checks.
"""

import os
import resource
import sys


def execute(seconds, command):
    if seconds <= 0 or not command:
        raise ValueError('a positive CPU allowance and a command are required')
    soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
    soft = seconds if soft == resource.RLIM_INFINITY else min(seconds, soft)
    hard = seconds + 1 if hard == resource.RLIM_INFINITY else min(seconds + 1, hard)
    resource.setrlimit(resource.RLIMIT_CPU, (min(soft, hard), hard))
    os.execvp(command[0], command)


if __name__ == '__main__':
    try:
        if len(sys.argv) < 4 or sys.argv[2] != '--':
            raise ValueError('usage: cpu-limit.py <CPU seconds> -- <command> [args...]')
        execute(int(sys.argv[1]), sys.argv[3:])
    except (OSError, ValueError) as error:
        print(f'cpu-limit: {error}', file=sys.stderr)
        sys.exit(2)
