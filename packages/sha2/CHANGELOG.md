# sha2 changelog

Newest first. The name stays `sha2` at major 2: the v2-in-name rule asks the
name to end in its major, and the `2` of SHA-2 already does. A major 3 would
have to decide the name again.

## 2.0.1 (2026-10-05)

About 7 times faster on the native backend and 2 times on the JVM, with the
same digests. The block, the message schedule and the round constants are no
longer `List`s: a `List` read is a trie lookup, and the native backend spent
most of its time on them (64 MiB took 36 s, now 2 s). No API change.

## 2.0.0 (2026-08-16)

`Digest` is opaque over a private record; code that read or built its fields
no longer compiles. `new`, `update`, `finish` and `hex` are unchanged.

## 1.0.0 (2026-07-28)

SHA-256 in Dawn for the package manager's `d1:` tree hash, replacing
`java.security.MessageDigest`. Why it is a package and not a host service or
a std module: [`docs/package-design.md`](../../docs/package-design.md), section 9
(in Chinese).
