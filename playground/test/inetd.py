#!/usr/bin/env python3
"""Start a program per connection on a unix socket, the connection as its
stdin and stdout: what systemd does for dawn-play-native.socket (Accept=yes,
StandardInput/Output=socket), for the tests that drive the runner locally.

    inetd.py <socket path or abstract name> <program> [args...]

A first argument without a `/` is a name in Linux's abstract socket namespace
(curl --abstract-unix-socket): no file, and no 107-byte path limit to trip
over in a deep TMPDIR.

Why not `systemd-socket-activate -a --inetd`, which is the same thing: it is
not on every machine the contract runs on (a container without systemd has
none), and a test that is skipped where its tool is missing is a test that
quietly does not run. This is the standard library and nothing else. The
child gets this process's environment, its stderr and default signal
dispositions; the parent reaps each child as it exits (SIGCHLD), so none is
left a zombie for whoever inherits it when the test kills this process.
"""
import os, signal, socket, sys


def reap(_signum, _frame):
    try:
        while os.waitpid(-1, os.WNOHANG)[0]:
            pass
    except ChildProcessError:
        pass


def main(argv):
    if len(argv) < 3:
        print("usage: inetd.py <socket path> <program> [args...]", file=sys.stderr)
        return 2
    path, prog = argv[1], argv[2:]
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path if "/" in path else "\0" + path)
    srv.listen(64)
    signal.signal(signal.SIGCHLD, reap)
    while True:
        conn, _ = srv.accept()
        pid = os.fork()
        if pid == 0:
            try:
                srv.close()
                os.dup2(conn.fileno(), 0)
                os.dup2(conn.fileno(), 1)
                conn.close()
                for s in (signal.SIGCHLD, signal.SIGPIPE, signal.SIGINT):
                    signal.signal(s, signal.SIG_DFL)
                os.execvp(prog[0], prog)
            finally:
                os._exit(127)
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
