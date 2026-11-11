"""Exercise foreground input and shell job control through a real terminal."""
import fcntl
import os
from pathlib import Path
import pty
import select
import shlex
import subprocess
import termios
import time

from signals import cleanup, descendants, until


def claim_terminal():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class Terminal:
    def __init__(self, root):
        self.master, slave = pty.openpty()
        self.pending = b""
        self.transcript = b""
        self.prompt = b"DAWN_TTY_PROMPT> "
        env = {**os.environ, "PS1": self.prompt.decode(), "PROMPT_COMMAND": "", "TERM": "dumb"}
        self.proc = subprocess.Popen(["/bin/bash", "--noprofile", "--norc", "-i"], cwd=root,
                                     env=env, stdin=slave, stdout=slave, stderr=slave,
                                     preexec_fn=claim_terminal)
        os.close(slave)
        self.read_until(self.prompt)

    def send(self, data):
        os.write(self.master, data)

    def read_until(self, marker):
        deadline = time.monotonic() + 60
        while marker not in self.pending:
            left = deadline - time.monotonic()
            assert left > 0 and select.select([self.master], [], [], left)[0], self.transcript
            data = os.read(self.master, 4096)
            assert data, self.transcript
            self.pending += data
            self.transcript += data
        before, self.pending = self.pending.split(marker, 1)
        return before + marker

    def launch(self, binary, source, background=False):
        command = shlex.join([str(binary), "run", str(source)])
        if background:
            command += " &"
        self.send((command + "\n").encode())
        self.read_until(b"TTY_READY\r\n")
        driver = until(lambda: next(iter(descendants(self.proc.pid)), None))
        return driver

    def foreground_child(self, driver):
        def ready():
            foreground = os.tcgetpgrp(self.master)
            return foreground in descendants(driver) and foreground != driver
        until(ready)

    def restored(self):
        assert os.tcgetpgrp(self.master) == self.proc.pid

    def close(self):
        cleanup(self.proc, descendants(self.proc.pid))
        os.close(self.master)


def stopped(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] == "T"
    except FileNotFoundError:
        return False


def check(binary, root):
    source = root / "terminal.dawn"
    source.write_text('use std/io\npub fn main() -> Unit !io = {\n'
                      '  println("TTY_READY")\n'
                      '  let line = io.read_line().unwrap_or("")\n'
                      '  println("TTY_LINE=" ++ line)\n}\n')
    terminal = Terminal(root)
    try:
        driver = terminal.launch(binary, source)
        terminal.foreground_child(driver)
        terminal.send(b"terminal input\n")
        terminal.read_until(b"TTY_LINE=terminal input\r\n")
        terminal.read_until(terminal.prompt)
        terminal.restored()
        print("PASS terminal input and foreground restoration", flush=True)

        driver = terminal.launch(binary, source)
        terminal.foreground_child(driver)
        terminal.send(b"\x03")
        terminal.read_until(terminal.prompt)
        terminal.send(b"printf 'TTY_STATUS=%s\\n' \"$?\"\n")
        terminal.read_until(b"TTY_STATUS=130\r\n")
        terminal.read_until(terminal.prompt)
        terminal.restored()
        print("PASS terminal interrupt returns 130", flush=True)

        driver = terminal.launch(binary, source)
        terminal.foreground_child(driver)
        terminal.send(b"\x1a")
        terminal.read_until(terminal.prompt)
        until(lambda: stopped(driver))
        terminal.restored()
        terminal.send(b"bg\n")
        terminal.read_until(terminal.prompt)
        until(lambda: stopped(driver))
        terminal.restored()
        terminal.send(b"fg\n")
        terminal.foreground_child(driver)
        terminal.send(b"resumed input\n")
        terminal.read_until(b"TTY_LINE=resumed input\r\n")
        terminal.read_until(terminal.prompt)
        terminal.restored()
        print("PASS terminal suspend, background read stop and foreground resume", flush=True)

        driver = terminal.launch(binary, source, background=True)
        until(lambda: stopped(driver))
        terminal.restored()
        terminal.send(b"fg\n")
        terminal.foreground_child(driver)
        terminal.send(b"background input\n")
        terminal.read_until(b"TTY_LINE=background input\r\n")
        terminal.read_until(terminal.prompt)
        terminal.restored()
        print("PASS background launch resumes with foreground input", flush=True)
    finally:
        terminal.close()
