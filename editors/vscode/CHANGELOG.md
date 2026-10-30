# Changelog

## 0.1.6

- Open embedded standard-library definitions as read-only source documents,
  with semantic highlighting, hover and navigation from the same server snapshot.

## 0.1.5

- Three inlay hint settings, passed to the server as
  `initializationOptions.inlayHints` with the server's own defaults:
  `dawn.inlayHints.propagatedErrors` (the error type a `?` propagates; off),
  `dawn.inlayHints.declarationEffects` (the `!io` inferred for a private
  function that writes neither a return type nor effects; on) and
  `dawn.inlayHints.patternTypes` (the types of `for` and `match` bindings; on).
  The server reads these only at `initialize`, so changing one restarts it.
  A `dawn` that predates a hint ignores its setting.

## 0.1.4

- The output channel (Dawn Language Server) now says which server is running:
  the value of `dawn.lspPath`, the settings layer it came from, the file that
  starts (symlinks resolved), and the name and version the server reports at
  `initialize`. A server that reports no version, or one older than the
  extension expects, gets one warning per window. Every `dawn` up to 0.83.0
  reports none, so expect that warning until the next release.
- Changing `dawn.lspPath` restarts the server; it no longer waits for a window
  reload.
- `dawn.lspPath` expands `~`, `${userHome}` and `${workspaceFolder}`, and a
  relative path is taken from the first workspace folder rather than from
  wherever VS Code happened to start.

## 0.1.3

- Semantic highlighting from the language server. Names are coloured by what
  they resolve to rather than by their case: a constructor, a constant, a
  trait, an effect and a type no longer all look like a type, and a call looks
  like a function wherever it appears. `var` bindings and handler state cells
  are underlined (the `mutable` modifier). Keywords, literals and comments keep
  the TextMate grammar's colours, and so does everything while the server has
  not analysed the file yet. Needs a `dawn` whose `lsp` offers semantic tokens.

Earlier releases (0.1.0 to 0.1.2) have no entries here.
