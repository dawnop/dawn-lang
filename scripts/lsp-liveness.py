#!/usr/bin/env python3
"""Eight assertions about the language server's *scheduling*, which every other
LSP gate is blind to.

scripts/selfhost-lsp-diff.sh compares output bytes; a server that answers
correctly and then spins a core, or one that never notices its client left, is
byte-identical to a well-behaved one. Those are the two failure modes a
debounced read loop can introduce (docs/audit/lsp-robustness-design.md §2.2),
so the first three experiments existed *before* the loop changed, recording the
undebounced numbers as the baseline the change had to hold.

  hangup    after the client closes its end, the server exits 0 by itself.
  liveness  before the silent window starts, the server has already published
            diagnostics.
  idle      over the silent window, the server's CPU time stays near zero.
  debounce  a burst of edits is analysed fewer times than it has edits.
  freshness the one analysis it does run is of the *newest* text.
  cancel    a request the client cancelled while it still waited in the queue
            is answered RequestCancelled, and does not get its text analysed.
  coalesce  two edits with a code action after each are analysed once, as the
            newer text; code actions read the text, not the analysis.
  order     an edit, a hover, an edit: the hover answers the text it was asked
            about, so both texts are analysed, in order.

They are reported separately and on purpose, because each is red for its own
reason and none of them covers another. `liveness` is load-bearing rather than
decorative: `sh -c 'cat >/dev/null'` passes `hangup` and `idle` outright,
because doing nothing is both prompt and cheap. `debounce` and `freshness`
split the same way -- a loop that coalesced by keeping the *first* pending edit
instead of the last would pass `debounce` and publish stale diagnostics
forever.

The last three are about the queue rather than time (#790,
docs/audit/lsp-robustness-design.md §六 step 3): each writes its frames in one
burst, so all of them are waiting when the server reads the first, and they
split the same way. `cancel` and `coalesce` are red on a loop that analyses
before every request it reads; `order` is the guard on the other side, red on a
loop that lets a request jump the edit queued behind it, which would answer a
hover or a rename against a text it was not asked about.

Usage:  scripts/lsp-liveness.py [server command...]      (default ./bin/dawn lsp)

Linux only: the idle assertion reads utime+stime from /proc/<pid>/stat, and
there is no portable substitute. CI runs ubuntu-latest.
"""
import json
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
# the C and JVM stand-ins. The claim under test is "closing stdin makes the
# server exit", not "it exits fast", so this is a give-up bound, not a latency
# budget. It was 5s (~80x the observed worst case), and that still went red on
# a well-behaved server on a shared machine at load average ~30, where a JVM
# that has been told to exit can wait seconds for a core. Scaling by
# os.getloadavg() was the other option and was not taken: the load average is
# a one-minute trailing mean of the whole machine (on WSL2 it also counts
# D-state tasks), not the CPU this process is getting now, so it would make
# the threshold a guess about the scheduler that differs per machine.
#
# 60s (STARTUP_LIMIT_S, the bound for the same JVM doing far more work) keeps
# the `hang` mutant red -- it never exits, so any finite bound catches it --
# and costs nothing on the green path, which returns the moment the server
# exits. What the old bound also carried, "the exit was caused by the close",
# is asserted directly instead: the server must still be running when stdin
# is closed (an exit before it proves nothing about hangup handling), and it
# must end by exiting 0 on its own (a crash or a signal is not noticing EOF).
HANGUP_LIMIT_S = 60.0

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
# server.dawn currently sets to 50.
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
# 30 ms is 1.5x above the floor and 20 ms below the 50 ms window. It was 60 ms
# against the old 150 ms window; a gap at or above the window would assert the
# wrong thing (the third row).
EDITS = 5
KEYSTROKE_GAP_S = 0.03

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
        if srv.proc.poll() is not None:
            results.append(("hangup", False,
                            "exited with status %d before the client closed "
                            "stdin, so the close cannot have caused it"
                            % srv.proc.returncode, head_of_stdout(srv)))
            return
        srv.close_stdin()
        t0 = time.time()
        try:
            rc = srv.proc.wait(timeout=HANGUP_LIMIT_S)
            dt = time.time() - t0
            if rc == 0:
                results.append(("hangup", True,
                                "exited 0 %.2fs after the client closed stdin "
                                "(give-up bound %.0fs)" % (dt, HANGUP_LIMIT_S),
                                None))
            else:
                results.append(("hangup", False,
                                "ended with status %d %.2fs after the client "
                                "closed stdin -- a crash or a signal, not a "
                                "clean exit on end of input" % (rc, dt),
                                head_of_stdout(srv)))
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


# ---- the queue experiments (#790) ------------------------------------------
#
# How long to let a burst be answered: one or two analyses of a one-line file
# and the replies, ~0.2s measured; the wait ends as soon as stdout has been
# still for STDOUT_QUIET_S.
BURST_SETTLE_S = 30.0

# v1 of the `order` text has a function only it declares, and the hover asks
# about it; v2 does not have it, so the hover's answer says which text it read.
ORDER_V1 = "pub fn only_in_one() -> Int = 1\\npub fn main() -> Unit = zzz_1()\\n"


def request(rid, method, params):
    return frame('{"jsonrpc":"2.0","id":%d,"method":"%s","params":%s}'
                 % (rid, method, params))


def text_document():
    return '{"textDocument":{"uri":"%s"}' % DOC_URI


def messages(data):
    """The JSON messages in a stretch of server stdout, in order."""
    out = []
    while True:
        head = data.find(b"\r\n\r\n")
        if head < 0:
            return out
        length = None
        for line in data[:head].split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
        body = data[head + 4:head + 4 + (length or 0)]
        if length is None or len(body) < length:
            return out
        out.append(json.loads(body))
        data = data[head + 4 + length:]


def publishes(msgs):
    return [m["params"] for m in msgs
            if m.get("method") == "textDocument/publishDiagnostics"]


def reply(msgs, rid):
    for m in msgs:
        if m.get("id") == rid and "method" not in m:
            return m
    return None


def burst(cmd, names, results, payload):
    """Start a server, let it publish the opened document once and go quiet,
    then write `payload` in one go. Returns the messages that answered it, or
    None after recording every name in `names` as failed."""
    srv = Server(cmd)
    try:
        srv.send(HANDSHAKE)
        if srv.await_output(b"publishDiagnostics", STARTUP_LIMIT_S) is None or \
                not srv.await_quiet(STDOUT_QUIET_S, STARTUP_LIMIT_S):
            for name in names:
                results.append((name, False, "the server never published the "
                                "opened document and went quiet",
                                head_of_stdout(srv)))
            return None
        before = len(srv.stdout_bytes())
        srv.send(payload)
        srv.await_output(b"publishDiagnostics", BURST_SETTLE_S)
        srv.await_quiet(STDOUT_QUIET_S, BURST_SETTLE_S)
        return messages(srv.stdout_bytes()[before:])
    finally:
        srv.kill()


def versions(msgs):
    return [p.get("version") for p in publishes(msgs)]


def exp_cancel(cmd, results):
    """didChange v1, semanticTokens K, $/cancelRequest K, didChange v2.

    VS Code's order: it cancels a request the moment the content changes and
    sends the change itself up to 250 ms later. A loop that analyses before
    every request it reads analyses v1 for K, which nobody wants any more."""
    rid = 101
    msgs = burst(cmd, ["cancel"], results,
                 did_change(1, edit_text(1))
                 + request(rid, "textDocument/semanticTokens/full", text_document() + "}")
                 + frame('{"jsonrpc":"2.0","method":"$/cancelRequest","params":{"id":%d}}' % rid)
                 + did_change(2, edit_text(2)))
    if msgs is None:
        return
    got = reply(msgs, rid)
    code = (got or {}).get("error", {}).get("code")
    vs = versions(msgs)
    ok = code == -32800 and vs == [2]
    results.append(("cancel", ok,
                    "the cancelled request got %s; versions published after "
                    "the burst: %s (want error -32800 and [2])"
                    % ("no reply" if got is None else
                       "error %s" % code if code is not None else "a result", vs),
                    None if ok else "        stdout: " + json.dumps(msgs)[:400]))


def exp_coalesce(cmd, results):
    """didChange v1, codeAction, didChange v2, codeAction: one analysis, of v2."""
    action = ('{"textDocument":{"uri":"%s"},"range":{"start":{"line":0,"character":0},'
              '"end":{"line":0,"character":0}},"context":{"diagnostics":[]}}' % DOC_URI)
    msgs = burst(cmd, ["coalesce"], results,
                 did_change(1, edit_text(1)) + request(201, "textDocument/codeAction", action)
                 + did_change(2, edit_text(2)) + request(202, "textDocument/codeAction", action))
    if msgs is None:
        return
    answered = [rid for rid in (201, 202) if "result" in (reply(msgs, rid) or {})]
    pubs = publishes(msgs)
    named = json.dumps(pubs[-1]) if pubs else ""
    ok = answered == [201, 202] and len(pubs) == 1 and "zzz_2" in named
    results.append(("coalesce", ok,
                    "code actions answered: %s; %d analyses for 2 edits, the "
                    "last naming %s (want both, 1, zzz_2)"
                    % (answered, len(pubs),
                       "zzz_2" if "zzz_2" in named else "zzz_1" if "zzz_1" in named else "neither"),
                    None if ok else "        stdout: " + json.dumps(msgs)[:400]))


def exp_order(cmd, results):
    """didChange v1, hover on a name only v1 has, didChange v2."""
    hover = text_document() + ',"position":{"line":0,"character":8}}'
    msgs = burst(cmd, ["order"], results,
                 did_change(1, ORDER_V1) + request(301, "textDocument/hover", hover)
                 + did_change(2, edit_text(2)))
    if msgs is None:
        return
    got = json.dumps((reply(msgs, 301) or {}).get("result"))
    vs = versions(msgs)
    ok = "only_in_one" in got and vs == [1, 2]
    results.append(("order", ok,
                    "the hover %s `only_in_one`; versions published: %s "
                    "(want it named and [1, 2])"
                    % ("names" if "only_in_one" in got else "does not name", vs),
                    None if ok else "        stdout: " + json.dumps(msgs)[:400]))


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
    exp_cancel(cmd, results)
    exp_coalesce(cmd, results)
    exp_order(cmd, results)
    for name, ok, why, detail in results:
        print("%-9s %s -- %s" % (name + ":", "PASS" if ok else "FAIL", why))
        if detail:
            print(detail)
    bad = [n for n, ok, _, _ in results if not ok]
    if bad:
        print("lsp-liveness: FAILED (%s)" % ", ".join(bad))
        return 1
    print("lsp-liveness: OK (hangup, liveness, idle, debounce, freshness, "
          "cancel, coalesce, order)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
