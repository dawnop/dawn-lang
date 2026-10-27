# comptime Bytes contract

`run.sh` checks byte literals with the JVM compiler, both runtime backends,
classfile linking and access checks, and native ASan. `--native-host` uses
`DAWNC_BIN` to repeat the value and refusal cases with a compiler built from
current source. The existing byte packing and native selfhost gates invoke
the two legs.

The generated project checks independent integer and IEEE packing vectors,
UTF-8 validity and replacement, Buf chunk boundaries and forks, SHA padding
boundaries, imported and nested constants, all octets, 1 MiB payloads, many
small constants, and a 5000-element Bytes list. Python `struct`, `ctypes` and
`hashlib` supply expected bits and digests; results are never recorded from
a compiler run. NaN payload equality is required at width eight only.

Two compiling controls remove the logical allocation guard and the JVM
literal payload. Each must change the owning observable result. The mutator
registry participates in the common anchor preflight.
