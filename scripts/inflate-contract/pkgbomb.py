#!/usr/bin/env python3
# Package-archive bombs for the pkgfetch leg of run.sh (#405).
#
#   pkgbomb.py targz <out> <mib>
#   pkgbomb.py zip <out> <mib>
#
# Both expand to <mib> MiB of 0xFF from about a megabyte. 0xFF and not zero
# because the decompressor builds into an Array[Int], where 0..127 are shared
# boxes on the JVM and 128..255 each cost an object of their own: the high
# byte is the worst case for memory per output byte, and a ceiling that holds
# for it holds for every input.
#
# The zip is the hostile shape rather than an honest one: its directory claims
# the entry is 1000 bytes, so every check made before decompressing passes and
# only the ceiling handed to the decompressor stands between it and the heap.
# The tar.gz needs no lie, because pkgfetch gunzips the whole stream before it
# reads a single ustar header.
#
# Python and not the JVM probe: these have to be a .tar.gz and a .zip on disk
# for `dawn add file://...` to fetch, and both are streamed out a megabyte at a
# time, so this process never holds the expansion either.
import struct
import sys
import tarfile
import gzip
import zlib

CHUNK = b"\xff" * (1 << 20)


class Fill:
    """A file object of n 0xFF bytes, read without materialising them."""

    def __init__(self, n):
        self.n = n

    def read(self, k=-1):
        if k < 0 or k > self.n:
            k = self.n
        self.n -= k
        return b"\xff" * k


def targz(path, n):
    with open(path, "wb") as raw:
        gz = gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0)
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as t:
            info = tarfile.TarInfo("bomb-1.0.0/bomb.bin")
            info.size = n
            t.addfile(info, Fill(n))
        gz.close()


def lying_zip(path, n):
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = bytearray()
    crc = 0
    left = n
    while left:
        k = min(left, len(CHUNK))
        data += co.compress(CHUNK[:k])
        crc = zlib.crc32(CHUNK[:k], crc)
        left -= k
    data += co.flush()
    name = b"bomb-1.0.0/bomb.bin"
    declared = 1000
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0,
                        crc, len(data), declared, len(name), 0) + name
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 8, 0, 0,
                          crc, len(data), declared, len(name), 0, 0, 0, 0, 0, 0) + name
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1,
                      len(central), len(local) + len(data), 0)
    with open(path, "wb") as f:
        f.write(local + data + central + end)


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("targz", "zip"):
        sys.exit("usage: pkgbomb.py targz|zip <out> <mib>")
    n = int(sys.argv[3]) << 20
    if sys.argv[1] == "targz":
        targz(sys.argv[2], n)
    else:
        lying_zip(sys.argv[2], n)


if __name__ == "__main__":
    main()
