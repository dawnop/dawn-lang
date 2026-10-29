# Migrate to web 9

The manifest identity is `web9` 9.0.0. Keep the `web` dependency alias and
imports. Upgrade the web URL/subdir dependency, version, content hash and
lockfile together, using a release whose seed supports `Loc` and `caller()`.
The JVM adapter remains `web_jvm2` 2.0.0; use it from the same release tag
so its path dependency resolves to the same web package.

`text`, `json_response`, `raw`, `binary`, `streaming`, `with_header`,
`redirect`, `try_redirect`, `attachment` and `error_response` gain a trailing
`at: Loc = caller()`. Direct calls may omit it. Function values now take
that extra argument, supplied with `std/loc.here()` or a forwarded `Loc`.
Wrappers that report on behalf of their caller declare `at: Loc = caller()`
and pass `at = at` to the constructor. No compatibility layer is provided.
`json_ok` and `try_with_header` keep their signatures.

An illegal header, content type, status or stream length now panics at the
public constructor call. `error_response` attributes an illegal header in
an HttpError to the rendering call, since the error record stores no source
location. `try_redirect` still returns 400 for an illegal Location and panics
for an illegal status. Returned errors do not gain a location suffix.

## dawnop-site

In a separate upgrade after the formal toolchain release, bump the web
identity to `web9`, the version to 9.0.0, the URL tag/hash and the lockfile
entry. Keep the `web` alias and use the JVM adapter from the same tag.
Audit constructor function values for the extra `Loc`, and wrappers for
explicit forwarding. Direct calls need no added argument. If upgrading
from web 7, also apply the source protocol migration below. This change
does not edit or release dawnop-site.

## Previous migration: web 8 and web_jvm 2

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

### dawnop-site at the web 8 migration

At that migration, the site pinned web 7.2 and web_jvm 1.1 through its toolchain release.
It consumes this change in S7 after the next formal release, updating both
URL/subdir dependencies, versions, hashes and the lockfile together. Existing
`input_source` calls keep their signature, but custom BodySource callbacks,
direct reads and source-shape mutation fixtures must adopt `(pos, n)`.
S7 can replace Java stream state in shared code with a Bytes/file source;
its JVM adapter may keep InputStream behind `input_source`. A site pinned
to its current release keeps using that release until its separate upgrade.
