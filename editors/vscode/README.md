# Dawn for VS Code

Language support for [Dawn](https://github.com/dawnop/dawn-lang): a small,
elegant functional language with immutable data, algebraic data types with
exhaustive pattern matching, and effects written into the type signature.

- Syntax highlighting, brackets, comments and indentation.
- Diagnostics as you type, hover (types and signatures), go to definition, and
  the document outline, from the language server built into the Dawn compiler.

The front end does full error recovery, so a file that does not parse still
reports all of its errors instead of stopping at the first one.

## Requirements

This extension is a client. It does not carry a compiler, so install the Dawn
toolchain and make sure `dawn` is on the PATH VS Code sees. The two shortest
routes, both with the checksum the release publishes beside the artifact, are in
the [project README](https://github.com/dawnop/dawn-lang#install).

If `dawn` is not on VS Code's PATH, set **Dawn: Lsp Path** (`dawn.lspPath`) in
settings to the absolute path of the executable. The extension runs
`<dawn.lspPath> lsp` and speaks LSP over stdio.

The `dawnc` binary from the same release also answers `lsp` and can be used
here, with the caveat that it is the C backend and refuses `use java`.

## Settings

| Setting | Default | What it is |
|---|---|---|
| `dawn.lspPath` | `dawn` | The Dawn CLI to run the language server from. |

## Building it yourself

The extension source is in
[`editors/vscode`](https://github.com/dawnop/dawn-lang/tree/main/editors/vscode).
`npm ci && npm test` runs the TextMate scope contract, which asserts the grammar
against a corpus using VS Code's own TextMate engine; `npm run package` produces
the `.vsix`.

## License

[Apache-2.0](LICENSE), the same as the rest of the repository.
