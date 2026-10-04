# Dawn for VS Code

Language support for [Dawn](https://github.com/dawnop/dawn-lang): a small,
elegant functional language with immutable data, algebraic data types with
exhaustive pattern matching, and effects written into the type signature.

- Syntax highlighting, brackets, comments and indentation.
- Diagnostics as you type, hover (types and signatures, default values
  included), signature help inside a call's argument list, go to definition,
  and the document outline, from the language server built into the Dawn
  compiler.
- Semantic highlighting from the same server: names are coloured by what they
  resolve to (function, constructor, constant, trait or effect, parameter),
  not by their case, and `var` bindings are underlined.

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

To see which server is running, open the **Dawn Language Server** output
channel. Each start prints the setting's value and the settings layer it came
from, the file that runs (symlinks resolved), and the version the server
reports. If that is not the `dawn` you meant, the setting is either in a place
this window does not read (another profile, or another folder's workspace
settings) or names a file that does not exist.

The `dawnc` binary from the same release also answers `lsp` and can be used
here, with the caveat that it is the C backend and refuses `use java`.

## Settings

| Setting | Default | What it is |
|---|---|---|
| `dawn.lspPath` | `dawn` | The Dawn CLI to run the language server from. `~`, `${userHome}` and `${workspaceFolder}` are expanded; a relative path is taken from the first workspace folder; a change restarts the server. |

## Building it yourself

The extension source is in
[`editors/vscode`](https://github.com/dawnop/dawn-lang/tree/main/editors/vscode).
`npm ci && npm test` runs the TextMate scope contract, which asserts the grammar
against a corpus using VS Code's own TextMate engine, the semantic token
contract, which checks the manifest's declarations against the server's legend,
and the server contract, which covers how the executable is found and the
version check;
`npm run package` produces the `.vsix`.

## License

[Apache-2.0](LICENSE), the same as the rest of the repository.
