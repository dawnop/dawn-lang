#!/usr/bin/env python3
"""Five assertions about the language server's *scheduling*, which every other
LSP gate is blind to.

scripts/selfhost-lsp-diff.sh compares output bytes; a server that answers
correctly and then spins a core, or one that never notices its client left, is
byte-identical to a well-behaved one. Those are the two failure modes a
debounced read loop can introduce (docs/audit/lsp-robustness-design.md §2.2),
so the first three experiments existed *before* the loop changed, recording the
undebounced numbers as the baseline the change had to hold.

  hangup    after the client closes its end, the server exits within a limit.
  liveness  before the silent window starts, the server has already published
            diagnostics.
  idle      over the silent window, the server's CPU time stays near zero.
  debounce  a burst of edits is analysed fewer times than it has edits.
  freshness the one analysis it does run is of the *newest* text.

They are reported separately and on purpose, because each is red for its own
reason and none of them covers another. `liveness` is load-bearing rather than
decorative: `sh -c 'cat >/dev/null'` passes `hangup` and `idle` outright,
because doing nothing is both prompt and cheap. `debounce` and `freshness`
split the same way -- a loop that coalesced by keeping the *first* pending edit
instead of the last would pass `debounce` and publish stale diagnostics
forever.

Usage:  scripts/lsp-liveness.py [server command...]      (default ./bin/dawn lsp)

Linux only: the idle assertion reads utime+stime from /proc/<pid>/stat, and
there is no portable substitute. CI runs ubuntu-latest.
"""
import os
import subprocess
import sys
import tempfile
import time

# ---- limits, and where the numbers come from -------------------------------
#
# Measured 2026-08-04 on ./bin/dawn lsp (JVM backend, GraalVM 21.0.2, Linux
# 6.18 WSL2) and on the two stand-in loops of design §2.2.2.

# Exit delay after hangup: 0.06s measured for ./bin/dawn lsp, 0.00s / 0.02s for
# the C and JVM stand-ins. 5s is ~80x the observed worst case -- wide enough
# that a loaded CI runner cannot trip it, narrow enough that the `hang` mutant
# (which never exits at all) is caught by a mile.
HANGUP_LIMIT_S = 5.0

# Silent window and its CPU budget: 0.01-0.08s measured over six 6s windows.
# (The stand-ins answered 0.00s; the real server does not, so do not take that
# number as the floor.) A loop that polls instead of waiting burns a whole core
# -- a `spin` mutant of ./bin/dawn lsp measured 6.23s CPU over this window,
# 103.8%. 0.5s over 6s is 8% of one core: ~6x above the observed ceiling and
# ~12x below a real spin.
IDLE_WINDOW_S = 6.0
IDLE_CPU_LIMIT_S = 0.5

# How long the server may take to come up and publish its first diagnostics.
# Same cap as leg 5 of scripts/native-cli-diff.sh, which waits on the same
# event. Generous because ./bin/dawn may rebuild the toolchain first.
STARTUP_LIMIT_S = 60.0

# Between "diagnostics seen" and the start of the measured window: wait until
# stdout has been still this long. A fixed pause cannot work in both worlds --
# today three didChange frames mean three more analyses after the first
# publishDiagnostics (0.54s of them leaked into a 1.0s-pause window and failed
# the gate on a perfectly well-behaved server), while a debounced loop will
# answer them with one. Waiting for the output to settle is right either way,
# and a spin still shows up: a spinning loop is quiet on stdout and loud on the
# CPU, which is exactly the pair the idle assertion looks at.
STDOUT_QUIET_S = 1.5

# ---- the debounce experiment's numbers ------------------------------------
#
# EDITS keystrokes, KEYSTROKE_GAP_S apart, against a DEBOUNCE_MS window that
# server.dawn currently sets to 150.
#
# The gap is the whole experiment, and it has to sit between two floors that
# were measured (2026-08-05, ./bin/dawn lsp on this box) rather than guessed:
#
#   gap 0 (one burst)  every variant answers once, debounced or not -- the
#                      frames are already in the pipe when the loop asks, so
#                      the size of the window cannot matter. A gapless
#                      experiment proves nothing.
#   gap >= 0.02        a `DEBOUNCE_MS = 0` mutant publishes 5 of 5 again;
#                      the debounced server still publishes 1. Below that the
#                      analysis of edit k is still running when edit k+1
#                      lands, so the mutant coalesces by accident.
#   gap < window       otherwise the real server is *supposed* to publish
#                      every time and this asserts the wrong thing.
#
# 60 ms is 3x above the floor and 2.5x below the window, and it is also about
# what a fast typist actually does.
EDITS = 5
KEYSTROKE_GAP_S = 0.06

# How long to let the coalesced analysis land after the last edit. The window
# plus one analysis; 3s is ~10x the observed total.
DEBOUNCE_SETTLE_S = 3.0

TICKS = os.sysconf("SC_CLK_TCK")
DOC_URI = "file:///tmp/dawn-lsp-liveness.dawn"
DOC_TEXT = "pub fn main() -> Unit = ()\\n"

# The edit texts carry a marker each, so the *content* of the surviving
# analysis is checkable and not just its count: version k names `zzz_k`, which
# comes back as an undefined-function diagnostic naming it.
def edit_text(version):
    return "pub fn main() -> Unit = zzz_%d()\\n" % version


def frame(body):
    return ("Content-Length: %d\r\n\r\n%s" % (len(body), body)).encode()


HANDSHAKE = (
    frame('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}}')
    + frame('{"jsonrpc":"2.0","method":"initialized","params":{}}')
    + frame('{"jsonrpc":"2.0","method":"textDocument/didOpen","params":'
            '{"textDocument":{"uri":"%s","languageId":"dawn",'
            '"version":0,"text":"%s"}}}' % (DOC_URI, DOC_TEXT))
)


def did_change(version, text=DOC_TEXT):
    return frame('{"jsonrpc":"2.0","method":"textDocument/didChange","params":'
                 '{"textDocument":{"uri":"%s","version":%d},'
                 '"contentChanges":[{"text":"%s"}]}}'
                 % (DOC_URI, version, text))


def cpu_seconds(pid):
    """utime+stime of the whole thread group, in seconds, or None if it is gone.

    Fields are counted after the ") " that closes comm, because comm itself may
    contain spaces and parentheses.
    """
    try:
        with open("/proc/%d/stat" % pid) as f:
            fields = f.read().rsplit(") ", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / TICKS
    except (OSError, IndexError, ValueError):
        return None


class Server:
    """A spawned server plus its captured stdout, always cleaned up."""

    def __init__(self, cmd):
        self.out = tempfile.TemporaryFile()
        # own session: if the command is a wrapper that forks, the whole group
        # goes down with it rather than outliving this script in CI.
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=self.out,
                                     stderr=subprocess.DEVNULL,
                                     start_new_session=True)

    def send(self, payload):
        try:
            self.proc.stdin.write(payload)
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def stdout_bytes(self):
        self.out.seek(0)
        return self.out.read()

    def await_output(self, needle, deadline_s):
        """Wait for `needle` on stdout (b"" = any output at all). Returns the
        wait in seconds, or None on timeout / early exit."""
        t0 = time.time()
        while time.time() - t0 < deadline_s:
            data = self.stdout_bytes()
            if (needle and needle in data) or (not needle and data):
                return time.time() - t0
            if self.proc.poll() is not None:
                return None
            time.sleep(0.05)
        return None

    def await_quiet(self, quiet_s, deadline_s):
        """Wait until stdout has not grown for `quiet_s`. Returns False if the
        deadline passed with output still arriving."""
        t0 = time.time()
        last = len(self.stdout_bytes())
        still_since = time.time()
        while time.time() - t0 < deadline_s:
            time.sleep(0.1)
            now = len(self.stdout_bytes())
            if now != last:
                last = now
                still_since = time.time()
            elif time.time() - still_since >= quiet_s:
                return True
        return False

    def close_stdin(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass

    def kill(self):
        self.close_stdin()
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), 9)
            except OSError:
                self.proc.kill()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        self.out.close()


def head_of_stdout(srv, lines=4):
    data = srv.stdout_bytes()
    if not data:
        return "        stdout: (empty)"
    shown = data[:600].decode("utf-8", "replace").splitlines()[:lines]
    return "\n".join("        stdout: " + ln for ln in shown)


def exp_hangup(cmd, results):
    """The client goes away; the server must notice.

    The session is the shortest one that reaches the read loop -- handshake
    only, no didChange. End of input is a property of the read path, and a
    shorter session means fewer confounds standing between the close and the
    exit.
    """
    srv = Server(cmd)
    try:
        srv.send(HANDSHAKE)
        seen = srv.await_output(b"", STARTUP_LIMIT_S)
        srv.close_stdin()
        t0 = time.time()
        try:
            srv.proc.wait(timeout=HANGUP_LIMIT_S)
            dt = time.time() - t0
            results.append(("hangup", True,
                            "exited %.2fs after the client closed stdin "
                            "(limit %.2fs)" % (dt, HANGUP_LIMIT_S), None))
        except subprocess.TimeoutExpired:
            detail = ("        no stdout in %.0fs before the close, so the server "
                      "may never have started" % STARTUP_LIMIT_S) if seen is None \
                else head_of_stdout(srv)
            results.append(("hangup", False,
                            "still alive %.2fs after the client closed stdin "
                            "(limit %.2fs)" % (HANGUP_LIMIT_S, HANGUP_LIMIT_S),
                            detail))
    finally:
        srv.kill()


def exp_idle(cmd, results):
    """Connected but silent. Two assertions, measured in one session because
    the second is only meaningful given the first."""
    srv = Server(cmd)
    try:
        srv.send(HANDSHAKE)
        for v in range(1, 4):
            srv.send(did_change(v))
        waited = srv.await_output(b"publishDiagnostics", STARTUP_LIMIT_S)
        if waited is None:
            results.append(("liveness", False,
                            "no publishDiagnostics in %.0fs -- whatever this "
                            "process is, it never did the work the idle "
                            "measurement claims to be about"
                            % STARTUP_LIMIT_S, head_of_stdout(srv)))
        else:
            results.append(("liveness", True,
                            "published diagnostics %.2fs after start, before "
                            "the silent window" % waited, None))

        if not srv.await_quiet(STDOUT_QUIET_S, STARTUP_LIMIT_S):
            results.append(("idle", False,
                            "stdout never went still for %.1fs within %.0fs -- "
                            "the server is still answering, so there is no "
                            "silent window to measure"
                            % (STDOUT_QUIET_S, STARTUP_LIMIT_S),
                            head_of_stdout(srv)))
            return
        c0 = cpu_seconds(srv.proc.pid)
        if c0 is None:
            results.append(("idle", False,
                            "server was gone before the window opened -- "
                            "nothing to measure", head_of_stdout(srv)))
            return
        time.sleep(IDLE_WINDOW_S)
        c1 = cpu_seconds(srv.proc.pid)
        if c1 is None or srv.proc.poll() is not None:
            results.append(("idle", False,
                            "server exited during the %.1fs silent window -- "
                            "nothing to measure" % IDLE_WINDOW_S,
                            head_of_stdout(srv)))
            return
        used = c1 - c0
        ok = used <= IDLE_CPU_LIMIT_S
        results.append(("idle", ok,
                        "%.2fs CPU over a %.1fs silent window = %.1f%% of one "
                        "core (limit %.2fs)"
                        % (used, IDLE_WINDOW_S, 100.0 * used / IDLE_WINDOW_S,
                           IDLE_CPU_LIMIT_S),
                        None if ok else head_of_stdout(srv)))
    finally:
        srv.kill()


def exp_debounce(cmd, results):
    """A burst of edits, and what the server does with it.

    Two assertions off one session, and they fail for opposite reasons:

      debounce   fewer analyses than edits. Red when the loop answers every
                 keystroke -- which is what the server did before LSP-04, and
                 what a `DEBOUNCE_MS = 0` mutant of it does again (5 of 5,
                 measured).
      freshness  the surviving analysis is of the last edit. Red when the loop
                 coalesces toward the *oldest* pending text instead of the
                 newest -- a mutant that keeps `debounce` perfectly green
                 while pinning the editor's diagnostics to a text the user
                 left several keystrokes ago.

    Counting starts after the first publishDiagnostics rather than from the
    process start, so `didOpen`'s own analysis (and any warm-up before it) is
    outside the measurement: what is being counted is edits-to-analyses.
    """
    srv = Server(cmd)
    try:
        srv.send(HANDSHAKE)
        if srv.await_output(b"publishDiagnostics", STARTUP_LIMIT_S) is None:
            for name in ("debounce", "freshness"):
                results.append((name, False,
                                "no publishDiagnostics in %.0fs -- the server "
                                "never got as far as the edits"
                                % STARTUP_LIMIT_S, head_of_stdout(srv)))
            return
        before = srv.stdout_bytes().count(b"publishDiagnostics")
        for v in range(1, EDITS + 1):
            srv.send(did_change(v, edit_text(v)))
            time.sleep(KEYSTROKE_GAP_S)
        time.sleep(DEBOUNCE_SETTLE_S)

        data = srv.stdout_bytes()
        published = data.count(b"publishDiagnostics") - before
        ok = published < EDITS
        results.append(("debounce", ok,
                        "%d analyses for %d edits %.0fms apart"
                        % (published, EDITS, KEYSTROKE_GAP_S * 1000),
                        None if ok else head_of_stdout(srv)))

        # the diagnostics of the last frame the server wrote
        last = data.rfind(b"publishDiagnostics")
        tail = data[last:].decode("utf-8", "replace")
        newest = "zzz_%d" % EDITS
        if published == 0:
            results.append(("freshness", False,
                            "nothing was published after the edits, so there "
                            "is no analysis to be fresh", head_of_stdout(srv)))
        elif newest in tail:
            results.append(("freshness", True,
                            "the last diagnostics name `%s`, the newest edit"
                            % newest, None))
        else:
            stale = [k for k in range(0, EDITS) if ("zzz_%d" % k) in tail]
            results.append(("freshness", False,
                            "the last diagnostics do not mention `%s`; they "
                            "name %s -- the analysis that ran was of an edit "
                            "the client had already replaced"
                            % (newest, stale or "no edit at all"),
                            "        stdout: " + tail[:400].replace("\n", " ")))
    finally:
        srv.kill()


def main():
    if not os.path.exists("/proc/self/stat"):
        print("lsp-liveness: needs /proc (Linux); the idle assertion has no "
              "portable substitute", file=sys.stderr)
        return 2
    # `dawn lsp` reads std/ off the cwd, so run from the repo root the way
    # scripts/selfhost-lsp-diff.sh does. Give absolute paths for a server
    # outside the tree.
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    cmd = sys.argv[1:] or ["./bin/dawn", "lsp"]
    print("lsp-liveness: server = %s" % " ".join(cmd))
    results = []
    exp_hangup(cmd, results)
    exp_idle(cmd, results)
    exp_debounce(cmd, results)
    for name, ok, why, detail in results:
        print("%-9s %s -- %s" % (name + ":", "PASS" if ok else "FAIL", why))
        if detail:
            print(detail)
    bad = [n for n, ok, _, _ in results if not ok]
    if bad:
        print("lsp-liveness: FAILED (%s)" % ", ".join(bad))
        return 1
    print("lsp-liveness: OK (hangup, liveness, idle, debounce, freshness)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
