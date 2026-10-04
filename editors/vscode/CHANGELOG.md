# Changelog

## 0.1.3

- Semantic highlighting from the language server. Names are coloured by what
  they resolve to rather than by their case: a constructor, a constant, a
  trait, an effect and a type no longer all look like a type, and a call looks
  like a function wherever it appears. `var` bindings and handler state cells
  are underlined (the `mutable` modifier). Keywords, literals and comments keep
  the TextMate grammar's colours, and so does everything while the server has
  not analysed the file yet. Needs a `dawn` whose `lsp` offers semantic tokens.

Earlier releases (0.1.0 to 0.1.2) have no entries here.
