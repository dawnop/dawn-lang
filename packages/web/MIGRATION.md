# Migrate to web 8 and web_jvm 2

Upgrade both packages from one release tag and regenerate the lockfile.
The manifest identities are `web8` 8.0.0 and `web_jvm2` 2.0.0. Keep aliases
`web` and `web_jvm` so imports keep their existing paths. Do not combine a
web 7 source or server adapter with web 8.

Every `BodySource` literal must supply `read: (pos, n) => ...` instead of
`read: n => ...`. The pump owns the cumulative byte offset, starting at zero
and advancing by the actual returned length. Return at most `n` bytes,
return empty bytes only at EOF, and keep close responsible for the source's
resources. Short reads are valid. Direct source reads must pass both
arguments. There is no compatibility forwarding function.

For immutable Bytes, replace a stateful callback with
`web/source.bytes_source(data)`. For a file, use `file_source(path)`, backed
by `read_range(path, pos, n)`. It opens and closes each range independently,
does not own the path, and requires the file to remain unchanged until the
response ends. Wrap close when the source owns a temporary file. A failed
read becomes a caught pump panic, with the IO kind and message preserved.

For an InputStream, keep `web_jvm/server.input_source(stream)`; that adapter
accepts and ignores pos because the stream already advances its own cursor.
These are sequential sources, consumed once; the protocol adds no seek or
replay promise. A source still closes exactly once on success, failed reads
or writes, short/long streams, HEAD and statuses that withhold the body.

## dawnop-site

The site currently pins web 7.2 and web_jvm 1.1 through its toolchain release.
It consumes this change in S7 after the next formal release, updating both
URL/subdir dependencies, versions, hashes and the lockfile together. Existing
`input_source` calls keep their signature, but custom BodySource callbacks,
direct reads and source-shape mutation fixtures must adopt `(pos, n)`.
S7 can replace Java stream state in shared code with a Bytes/file source;
its JVM adapter may keep InputStream behind `input_source`. A site pinned
to its current release keeps using that release until its separate upgrade.
