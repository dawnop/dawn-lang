# Changelog

## 2.0.0

- **Breaking:** pair with `web8` 8.0.0 and its `BodySource.read(pos, n)`
  protocol. The manifest identity is `web_jvm2`; keep the `web_jvm` alias.
- The response pump passes its actual cumulative byte offset. `input_source`
  ignores it because InputStream already advances sequentially. Its public
  function signature and ready-byte behavior are unchanged.
- Custom sources and direct source reads must accept/pass the new position.
  See [migration](../web/MIGRATION.md). Both dependencies must use one tag.
