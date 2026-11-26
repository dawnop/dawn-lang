"""Deduplicate immutable validation inputs for exactly one launcher startup.

Keys contain actual bytes rather than paths, timestamps or mutable object
identities. Worker threads share the context and wait for one computation;
neither successful results nor refusals survive the next launcher call.
"""

from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock

ACTIVE = ContextVar('native_validation_memo', default=None)


class Memo:
    def __init__(self):
        self.values = {}
        self.lock = Lock()

    def run(self, key, compute):
        namespace, raw, *context = key
        # This bucket is only a lookup accelerator. Reuse still compares every
        # byte, including the middle, before accepting an existing computation.
        bucket = (namespace, len(raw), raw[:32], raw[-32:], *context)
        with self.lock:
            entries = self.values.setdefault(bucket, [])
            future = next((value for known, value in entries if known == raw), None)
            owner = future is None
            if owner:
                future = Future()
                entries.append((raw, future))
        if not owner:
            return future.result()
        try:
            value = compute()
            future.set_result(value)
            return value
        except BaseException as exc:
            future.set_exception(exc)
            raise


@contextmanager
def validation_scope():
    token = ACTIVE.set(Memo())
    try:
        yield ACTIVE.get()
    finally:
        ACTIVE.reset(token)


def startup(function):
    @wraps(function)
    def call(*args, **kwargs):
        with validation_scope():
            return function(*args, **kwargs)
    return call
