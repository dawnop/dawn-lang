// Thin LSP client shell: spawn `dawn lsp` and let vscode-languageclient do the rest.
//
// The one thing it adds is a watcher on the two manifest names. The document
// selector covers Dawn sources only, so saving dawn.toml reaches the server as
// nothing at all; the server re-plans a workspace on
// `workspace/didChangeWatchedFiles`. It also registers the same watcher
// dynamically when a client allows it, and vscode-languageclient batches both
// sources into one notification, which the server de-duplicates. This watcher
// is kept anyway so the refresh does not hinge on dynamic registration.
const vscode = require('vscode');
const { LanguageClient } = require('vscode-languageclient/node');

let client;

function activate(context) {
  const command = vscode.workspace.getConfiguration('dawn').get('lspPath', 'dawn');

  const manifests = vscode.workspace.createFileSystemWatcher('**/{dawn.toml,dawn.lock}');
  context.subscriptions.push(manifests);

  client = new LanguageClient(
    'dawn',
    'Dawn Language Server',
    { command, args: ['lsp'] },
    {
      documentSelector: [{ scheme: 'file', language: 'dawn' }],
      synchronize: { fileEvents: manifests },
    },
  );

  client.start();
  context.subscriptions.push({ dispose: () => client && client.stop() });
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
