# Editor integration

The language server ships inside the dawn CLI: any LSP client just needs to run
`dawn lsp` (stdio). Features today: diagnostics as you type, hover (types and
signatures), go to definition, document outline.

Choose the compiler explicitly:

- Installed native: follow the [project installation instructions](../README.md#install)
  for Linux x86_64, put its `bin` on PATH, and run `dawn lsp`. It refuses `use java`.
- Checkout: `./bin/dawn` is the JVM bootstrap driver. With JDK 21 or newer,
  `./bin/dawn --version` fetches the seed and builds the toolchain. Select its
  absolute path in the editor.
- Explicit JVM: with JDK 21 or newer, run
  `java -jar /absolute/versioned/dawn-selfhost.jar lsp` from a verified release.
  JDK options go before `-jar`.

The installed native command does not switch toolchains after a failure.

## VS Code

The extension source lives in [`vscode/`](vscode/). To build and install it:

```bash
cd editors/vscode
npm ci
npm run package
code --install-extension dawn-lang.vsix
```

The default is `dawn.lspPath = "dawn"` and `dawn.lspArgs = []`, which starts
`dawn lsp`. Select an installed executable or checkout driver by setting
`dawn.lspPath` to its absolute path. For an explicit JVM server:

```json
{
  "dawn.lspPath": "java",
  "dawn.lspArgs": ["-jar", "/absolute/versioned/dawn-selfhost.jar"]
}
```

The extension appends `lsp` and passes each argument literally without a shell.
Use an absolute JAR path; put JDK options before `-jar`. Both settings restart the
server when changed. The **Dawn Language Server** output channel records the
executable, resolved path, argv and server version at each start.

### Publishing it

`npm test` and `npm run package` run in `editor-grammar.yml` when editor files
change. Packaging checks the manifest; publishing separately requires credentials:

1. A publisher named `dawnop` on the Visual Studio Marketplace, created once at
   <https://marketplace.visualstudio.com/manage>. It must match `publisher` in
   `vscode/package.json`.
2. A Personal Access Token from the Azure DevOps organization that publisher
   belongs to, scoped to **Marketplace: Manage** and to *all* organizations.
3. `npx vsce login dawnop` once with that token, then `npm run package && npx
   vsce publish --packagePath dawn-lang.vsix` from `editors/vscode`.

Bump `version` in `vscode/package.json` before each publish; the Marketplace
rejects a re-upload of a version it already has. The extension's version is its
own and deliberately does not track the toolchain's: it is a thin LSP client and
a grammar, and it does not change on most releases.

## Neovim (0.10+)

```lua
vim.filetype.add({ extension = { dawn = "dawn" } })

vim.api.nvim_create_autocmd("FileType", {
  pattern = "dawn",
  callback = function()
    vim.lsp.start({
      name = "dawn",
      cmd = { "dawn", "lsp" },
      root_dir = vim.fs.root(0, { ".git" }),
    })
  end,
})
```

For a checkout in Neovim, replace `cmd` with
`{ "/absolute/checkout/bin/dawn", "lsp" }`. For an explicit JVM server, use
`{ "java", "-jar", "/absolute/versioned/dawn-selfhost.jar", "lsp" }`.

## Helix

```toml
# ~/.config/helix/languages.toml
[language-server.dawn]
command = "dawn"
args = ["lsp"]

[[language]]
name = "dawn"
scope = "source.dawn"
file-types = ["dawn"]
comment-token = "#"
language-servers = ["dawn"]
```

For a checkout in Helix, set `command = "/absolute/checkout/bin/dawn"` and keep
`args = ["lsp"]`. For an explicit JVM server, use:

```toml
[language-server.dawn]
command = "java"
args = ["-jar", "/absolute/versioned/dawn-selfhost.jar", "lsp"]
```

These clients also take argv arrays. Paths containing spaces stay in one element;
no shell wrapper is needed.
