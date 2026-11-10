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
routes, with release checksums and native installation verification, are in
the [project README](https://github.com/dawnop/dawn-lang#install).

If `dawn` is not on VS Code's PATH, set **Dawn: Lsp Path** (`dawn.lspPath`) in
settings to the absolute path of the executable. The extension runs
`<dawn.lspPath>` with `dawn.lspArgs` followed by `lsp`, and speaks LSP over stdio.
The default settings run the installed native command as `dawn lsp`.

To use a checkout's JVM bootstrap driver, set `dawn.lspPath` to its absolute
`bin/dawn` path and leave `dawn.lspArgs` empty. To use a release JAR explicitly:

```json
{
  "dawn.lspPath": "java",
  "dawn.lspArgs": ["-jar", "/absolute/versioned/dawn-selfhost.jar"]
}
```

Use a JDK 21 or newer `java`, or set its absolute path. Put any JDK options before
`-jar`. Each array element is passed literally, preserving empty strings, spaces
and Unicode, without a shell, variable expansion or extra quoting. Use an absolute
JAR path. Changing either setting restarts the server. Native capability errors
require an explicit toolchain choice; they do not select a JVM server.

To see which server is running, open the **Dawn Language Server** output
channel. Each start prints the setting's value and the settings layer it came
from, the file that runs (symlinks resolved), the exact argv array, and the
version the server reports. If that is not the `dawn` you meant, the setting is either in a place
this window does not read (another profile, or another folder's workspace
settings) or names a file that does not exist.

Installed `dawn` is the native C backend and refuses `use java`. The checkout
driver and explicit JAR run on the JVM and support Java interop.

## Settings

| Setting | Default | What it is |
|---|---|---|
| `dawn.lspPath` | `dawn` | The executable to run; the default selects the installed native CLI. `~`, `${userHome}` and `${workspaceFolder}` are expanded; a relative path is taken from the first workspace folder; a change restarts the server. |
| `dawn.lspArgs` | `[]` | Literal argv elements before the final `lsp`, with no shell or expansion. For Java, use `["-jar", "/absolute/versioned/dawn-selfhost.jar"]` and set `dawn.lspPath` to `java`. A change restarts the server. |
| `dawn.inlayHints.propagatedErrors` | `false` | Show the error type a `?` on a `Result` propagates, after the `?`. |
| `dawn.inlayHints.declarationEffects` | `true` | Show the `!io` the checker infers for a private function that writes neither a return type nor effects. |
| `dawn.inlayHints.patternTypes` | `true` | Show the types of the names a `for` pattern or a `match` arm binds. |

The three inlay hint settings go to the server as `initializationOptions`,
which it reads only when it starts, so changing one restarts the server. The
other inlay hints (types on `let` and lambda parameters, effects on calls,
left-out default arguments, parameter names) keep the server's defaults and
have no setting yet.

## Building it yourself

The extension source is in
[`editors/vscode`](https://github.com/dawnop/dawn-lang/tree/main/editors/vscode).
`npm ci && npm test` runs the TextMate scope contract, which asserts the grammar
against a corpus using VS Code's own TextMate engine, the semantic token
contract, which checks the manifest's declarations against the server's legend,
and the server contract, which covers how the executable is found and the
version check, literal launch arguments and configuration restarts;
`npm run package` produces the `.vsix`.

## License

[Apache-2.0](LICENSE), the same as the rest of the repository.
