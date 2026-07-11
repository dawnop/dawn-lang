// Thin LSP client shell: spawn `dawn lsp` and let vscode-languageclient do the rest.
const vscode = require('vscode');
const { LanguageClient } = require('vscode-languageclient/node');

let client;

function activate(context) {
  const command = vscode.workspace.getConfiguration('dawn').get('lspPath', 'dawn');

  client = new LanguageClient(
    'dawn',
    'Dawn Language Server',
    { command, args: ['lsp'] },
    { documentSelector: [{ scheme: 'file', language: 'dawn' }] },
  );

  client.start();
  context.subscriptions.push({ dispose: () => client && client.stop() });
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
