"""Kernel exit events and a real compiler's include-FIFO handshake."""
import ctypes
import os
import select
import threading
import time


READY_FD = "DAWN_SIGNAL_READY_FD"


def pidfd(pid):
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid, 0)
    # Some CI Python builds used older kernel headers. The host libc still
    # exposes the same operation; do not substitute a /proc state sample.
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.pidfd_open(pid, 0)
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return fd


def readable(fd, label, timeout=60):
    assert select.select([fd], [], [], timeout)[0], label


def wait_exited(handles, timeout=10):
    """Wait for every captured process, including its last thread, to exit."""
    pending = dict(handles)
    poll = select.poll()
    for fd in pending:
        poll.register(fd, select.POLLIN)
    deadline = time.monotonic() + timeout
    while pending:
        events = poll.poll(max(0, int((deadline - time.monotonic()) * 1000)))
        assert events, f"live descendants after driver exit: {list(pending.values())}"
        for fd, event in events:
            assert event & (select.POLLIN | select.POLLHUP), (pending[fd], event)
            poll.unregister(fd)
            del pending[fd]


class CompilerReady:
    """Keep the include unread until cancellation, after both peers arrive."""
    def __init__(self, fifo):
        self.fifo = fifo
        self.pid_read, self.pid_write = os.pipe()
        self.fifo_read, self.fifo_write = os.pipe()
        self.writer = None
        self.thread = threading.Thread(target=self.connect)

    def connect(self):
        self.writer = os.open(self.fifo, os.O_WRONLY)
        os.write(self.fifo_write, b"R")

    def __enter__(self):
        self.thread.start()
        return self

    def parent_started(self):
        os.close(self.pid_write)
        self.pid_write = None

    def wait(self):
        readable(self.pid_read, "compiler did not announce its PID")
        packet = os.read(self.pid_read, 4096)
        assert packet.endswith(b"\n") and packet.strip().isdigit(), packet
        readable(self.fifo_read, "compiler did not open its include FIFO")
        assert os.read(self.fifo_read, 1) == b"R"
        return int(packet)

    def __exit__(self, *unused):
        # On a startup failure no compiler may ever open the FIFO. Release
        # our own blocked writer before closing its notification descriptors.
        reader = None
        if self.thread.is_alive():
            reader = os.open(self.fifo, os.O_RDONLY | os.O_NONBLOCK)
        self.thread.join()
        for fd in (reader, self.writer, self.pid_read, self.pid_write,
                   self.fifo_read, self.fifo_write):
            if fd is not None:
                os.close(fd)
