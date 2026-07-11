# Editor integration

The language server ships inside the dawn CLI: any LSP client just needs to run
`dawn lsp` (stdio). Features today: diagnostics as you type, hover (types and
signatures), go to definition, document outline.

Make sure `bin/dawn` is on your PATH (or use an absolute path below), and build
the CLI first: `gradle :compiler:fatJar`.

## VS Code

The extension lives in [`vscode/`](vscode/). To run it from source:

```bash
cd editors/vscode
npm install
# open this folder in VS Code, then press F5 (Run Extension)
```

Or package and install it:

```bash
npx @vscode/vsce package
code --install-extension dawn-lang-0.1.0.vsix
```

If `dawn` is not on VS Code's PATH, set `dawn.lspPath` in settings to the
absolute path of `bin/dawn`.

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
