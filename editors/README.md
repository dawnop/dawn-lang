# Editor integration

The language server ships inside the dawn CLI: any LSP client just needs to run
`dawn lsp` (stdio). Features today: diagnostics as you type, hover (types and
signatures), go to definition, document outline.

Make sure `bin/dawn` is on your PATH (or use an absolute path below), and build
the CLI first: `./bin/dawn --version` (fetches the seed and builds the toolchain).

## VS Code

The extension lives in [`vscode/`](vscode/). **It is not on the Marketplace
yet**, so until it is, install it from a package you build. To run it from
source:

```bash
cd editors/vscode
npm ci
# open this folder in VS Code, then press F5 (Run Extension)
```

Or package and install it:

```bash
cd editors/vscode
npm ci
npm run package
code --install-extension dawn-lang.vsix
```

If `dawn` is not on VS Code's PATH, set `dawn.lspPath` in settings to the
absolute path of `bin/dawn`.

### Publishing it

`npm run package` runs on every push (`gates.yml`, the `editor-grammar` job), so
the manifest is known to be publishable at all times. Everything after that
needs credentials, which is why the extension is not published yet:

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
