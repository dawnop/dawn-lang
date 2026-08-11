#!/usr/bin/env python3
"""Apply one compiling source mutation to the compiler-weight sampler."""

from pathlib import Path
import sys


MUTATIONS = {
    "descendants-one-hop": (
        "DESCENDANT_DEPTH_LIMIT: int | None = None",
        "DESCENDANT_DEPTH_LIMIT: int | None = 1",
    ),
    "heap-parser-off-by-one": (
        '    if value <= 0:\n'
        '        raise BenchError("jcmd VM.flags returned a non-positive MaxHeapSize")\n'
        "    return value",
        '    if value <= 0:\n'
        '        raise BenchError("jcmd VM.flags returned a non-positive MaxHeapSize")\n'
        "    return value + 1",
    ),
    "tree-rss-last-only": (
        "                    tree_rss += view.rss_bytes",
        "                    tree_rss = view.rss_bytes",
    ),
    "overlap-any-role": (
        "                    if set(expected_roles).issubset(roles_now):",
        "                    if set(expected_roles).intersection(roles_now):",
    ),
    "sampling-200ms": (
        "PROC_INTERVAL_NS = 2_000_000",
        "PROC_INTERVAL_NS = 200_000_000",
    ),
    "starttime-constant": (
        "        starttime = int(fields[19])",
        "        starttime = 1",
    ),
    "vmhwm-constant": (
        '    return values["VmRSS"], values["VmHWM"], values["VmPeak"]',
        '    return values["VmRSS"], 1, values["VmPeak"]',
    ),
    "skip-exception-cleanup": (
        "            if not completed_normally:\n"
        "                terminate_process_group(process)",
        "            if not completed_normally:\n"
        "                process.poll()",
    ),
    "skip-post-cmdline-identity": (
        "    argv = cmdline_reader(stat.identity.pid)\n"
        "    if not identity_is_current(stat.identity, identity_reader):\n"
        "        return None\n"
        "    rss, hwm, peak = status",
        "    argv = cmdline_reader(stat.identity.pid)\n"
        "    rss, hwm, peak = status",
    ),
    "allow-inherited-java-home": (
        '    "JAVA_HOME",\n'
        '    "CLASSPATH",',
        '    "CLASSPATH",',
    ),
    "snapshot-fail-open": (
        "def verify_final_source_snapshot(expected_commit: str, root: Path = ROOT) -> None:\n"
        "    actual_commit = source_snapshot(root)\n"
        "    if actual_commit != expected_commit:\n"
        "        raise BenchError(\n"
        '            f"source HEAD changed during measurement: expected {expected_commit}, "\n'
        '            f"found {actual_commit}"\n'
        "        )",
        "def verify_final_source_snapshot(expected_commit: str, root: Path = ROOT) -> None:\n"
        "    del expected_commit, root",
    ),
}


def main() -> None:
    if sys.argv[1:] == ["--list"]:
        for name in MUTATIONS:
            print(name)
        return
    if len(sys.argv) != 3 or sys.argv[1] not in MUTATIONS:
        names = " | ".join(MUTATIONS)
        raise SystemExit(f"usage: mutate.py <{names}> <selfhost-bench.py>")
    mutation, raw_path = sys.argv[1:]
    path = Path(raw_path)
    text = path.read_text(encoding="utf-8")
    old, new = MUTATIONS[mutation]
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{mutation}: mutation anchor drifted ({count} matches)")
    path.write_text(text.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
