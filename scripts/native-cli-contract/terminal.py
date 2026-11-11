"""Exercise foreground input and shell job control through a real terminal."""
import fcntl
import os
import pty
import re
import select
import shlex
import signal
import subprocess
import termios
import time

from process_events import pidfd, wait_exited
from signals import cleanup, descendants


def claim_terminal():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class Terminal:
    def __init__(self, root):
        self.master, slave = pty.openpty()
        self.pending = b""
        self.transcript = b""
        self.prompt = b"DAWN_TTY_PROMPT> "
        self.drivers = {}
        env = {**os.environ, "PS1": self.prompt.decode(), "PROMPT_COMMAND": "", "TERM": "dumb"}
        self.proc = subprocess.Popen(["/bin/bash", "--noprofile", "--norc", "-i"], cwd=root,
                                     env=env, stdin=slave, stdout=slave, stderr=slave,
                                     preexec_fn=claim_terminal)
        os.close(slave)
        self.read_until(self.prompt)

    def send(self, data):
        os.write(self.master, data)

    def read_until(self, marker):
        pattern = re.compile(re.escape(marker)) if isinstance(marker, bytes) else marker
        deadline = time.monotonic() + 60
        while (match := pattern.search(self.pending)) is None:
            left = deadline - time.monotonic()
            assert left > 0 and select.select([self.master], [], [], left)[0], self.transcript
            data = os.read(self.master, 4096)
            assert data, self.transcript
            self.pending += data
            self.transcript += data
        before, self.pending = self.pending[:match.end()], self.pending[match.end():]
        return before

    def launch(self, binary, source, background=False):
        # The shell child announces its PID before exec, so neither compiler
        # startup nor a sample of /proc children stands in for job identity.
        command = "(printf 'TTY_DRIVER=%s\\n' \"$BASHPID\"; exec " + shlex.join(
            [str(binary), "run", str(source)]) + ")"
        if background:
            command += " &"
        self.send((command + "\n").encode())
        announced = self.read_until(re.compile(rb"TTY_DRIVER=(\d+)\r\n"))
        driver = int(re.search(rb"TTY_DRIVER=(\d+)\r\n", announced)[1])
        self.drivers[driver] = pidfd(driver)
        self.read_until(b"TTY_READY\r\n")
        return driver

    def foreground_child(self, driver):
        # Reading this line proves that the real program can read the tty.
        # It stays alive for the case's input or signal after acknowledging.
        self.send(b"TTY_PING\n")
        self.read_until(b"TTY_PONG\r\n")
        foreground = os.tcgetpgrp(self.master)
        assert foreground in descendants(driver) and foreground != driver, (driver, foreground)

    def wait_stopped(self, driver):
        # A leader's T state can precede Bash's wait status for the whole
        # job. fg must follow that status, otherwise Bash may see a running
        # job and omit SIGCONT. Have Bash acknowledge its own wait result.
        self.send(f"wait {driver}; printf 'TTY_STOPPED=%s:%s\\n' {driver} \"$?\"\n".encode())
        self.read_until(f"TTY_STOPPED={driver}:{128 + signal.SIGSTOP}\r\n".encode())
        self.read_until(self.prompt)

    def finished(self, driver):
        wait_exited({self.drivers[driver]: driver})

    def restored(self):
        assert os.tcgetpgrp(self.master) == self.proc.pid

    def close(self):
        cleanup(self.proc, descendants(self.proc.pid))
        for fd in self.drivers.values():
            os.close(fd)
        os.close(self.master)


def check(binary, root):
    source = root / "terminal.dawn"
    source.write_text('use std/io\npub fn main() -> Unit !io = {\n'
                      '  println("TTY_READY")\n'
                      '  var line = io.read_line().unwrap_or("")\n'
                      '  while line == "TTY_PING" {\n'
                      '    println("TTY_PONG")\n'
                      '    line = io.read_line().unwrap_or("")\n'
                      '  }\n'
                      '  println("TTY_LINE=" ++ line)\n}\n')
    terminal = Terminal(root)
    try:
        driver = terminal.launch(binary, source)
        terminal.foreground_child(driver)
        terminal.send(b"terminal input\n")
        terminal.read_until(b"TTY_LINE=terminal input\r\n")
        terminal.read_until(terminal.prompt)
        terminal.finished(driver)
        terminal.restored()
        print("PASS terminal input and foreground restoration", flush=True)

        driver = terminal.launch(binary, source)
        terminal.foreground_child(driver)
        terminal.send(b"\x03")
        terminal.read_until(terminal.prompt)
        terminal.finished(driver)
        terminal.send(b"printf 'TTY_STATUS=%s\\n' \"$?\"\n")
        terminal.read_until(b"TTY_STATUS=130\r\n")
        terminal.read_until(terminal.prompt)
        terminal.restored()
        print("PASS terminal interrupt returns 130", flush=True)

        driver = terminal.launch(binary, source)
        terminal.foreground_child(driver)
        terminal.send(b"\x1a")
        terminal.read_until(terminal.prompt)
        terminal.wait_stopped(driver)
        terminal.restored()
        terminal.send(b"bg\n")
        terminal.read_until(terminal.prompt)
        terminal.wait_stopped(driver)
        terminal.restored()
        terminal.send(b"fg\n")
        terminal.foreground_child(driver)
        terminal.send(b"resumed input\n")
        terminal.read_until(b"TTY_LINE=resumed input\r\n")
        terminal.read_until(terminal.prompt)
        terminal.finished(driver)
        terminal.restored()
        print("PASS terminal suspend, background read stop and foreground resume", flush=True)

        driver = terminal.launch(binary, source, background=True)
        terminal.wait_stopped(driver)
        terminal.restored()
        terminal.send(b"fg\n")
        terminal.foreground_child(driver)
        terminal.send(b"background input\n")
        terminal.read_until(b"TTY_LINE=background input\r\n")
        terminal.read_until(terminal.prompt)
        terminal.finished(driver)
        terminal.restored()
        print("PASS background launch resumes with foreground input", flush=True)
    finally:
        terminal.close()
