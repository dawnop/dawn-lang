// Thin LSP client shell: spawn `dawn lsp` and let vscode-languageclient do the rest.
//
// The one thing it adds is a watcher on the two manifest names. The document
// selector covers Dawn sources only, so saving dawn.toml reaches the server as
// nothing at all; the server re-plans a workspace on
// `workspace/didChangeWatchedFiles`. It also registers the same watcher
// dynamically when a client allows it, and vscode-languageclient batches both
// sources into one notification, which the server de-duplicates. This watcher
// is kept anyway so the refresh does not hinge on dynamic registration.
//
// The other is saying which server it started. Before every start it prints
// the setting's value, the layer it came from, and the file that will run;
// after `initialize` it prints the server's serverInfo, and warns once per
// window when that is missing or too old. A stale `dawn` on PATH looks like a
// broken compiler otherwise (server.js has the case that prompted this). A
// change to `dawn.lspPath` restarts the client, so the setting no longer
// waits for a window reload.
const os = require('os');
const fs = require('fs');
const vscode = require('vscode');
const { LanguageClient } = require('vscode-languageclient/node');
const server = require('./server');

let client;
let output;
let warned = false;

function describeCommand() {
  const config = vscode.workspace.getConfiguration('dawn');
  const raw = config.get('lspPath', 'dawn');
  const source = server.settingSource(config.inspect('lspPath'));
  const folders = vscode.workspace.workspaceFolders || [];
  const workspaceFolder = folders.length > 0 ? folders[0].uri.fsPath : '';
  const command = server.expandCommand(raw, { home: os.homedir(), workspaceFolder });
  const found = server.findExecutable(command, process.env, process.platform);
  let real = found;
  if (found) {
    try { real = fs.realpathSync(found); } catch (_) { real = found; }
  }
  return { raw, source, command, found, real };
}

function log(line) {
  output.appendLine(`[dawn] ${line}`);
}

function reportServer(c, resolved) {
  const info = c.initializeResult && c.initializeResult.serverInfo;
  if (info) {
    log(`server reports ${info.name} ${info.version}`);
  }
  const problem = server.serverInfoProblem(info);
  if (!problem) return;
  log(`warning: ${problem}`);
  log(`the running server is ${resolved.real || resolved.command}; set dawn.lspPath to a newer dawn`);
  if (warned) return;
  warned = true;
  const where = resolved.real || resolved.command;
  vscode.window
    .showWarningMessage(`Dawn: ${problem} (${where}).`, 'Show Output', 'Open Settings')
    .then((pick) => {
      if (pick === 'Show Output') output.show(true);
      if (pick === 'Open Settings') {
        vscode.commands.executeCommand('workbench.action.openSettings', 'dawn.lspPath');
      }
    });
}

async function startClient(manifests) {
  const resolved = describeCommand();
  log(`dawn.lspPath = ${JSON.stringify(resolved.raw)} (from ${resolved.source})`);
  if (resolved.found) {
    const link = resolved.real !== resolved.found ? ` -> ${resolved.real}` : '';
    log(`starting ${resolved.found}${link} lsp`);
  } else {
    const where = resolved.command.includes('/') || resolved.command.includes('\\')
      ? 'no executable file at that path'
      : 'not found on PATH';
    log(`starting ${resolved.command} lsp (${where}; the start will likely fail)`);
  }

  const c = new LanguageClient(
    'dawn',
    'Dawn Language Server',
    { command: resolved.found || resolved.command, args: ['lsp'] },
    {
      documentSelector: [{ scheme: 'file', language: 'dawn' }],
      synchronize: { fileEvents: manifests },
      outputChannel: output,
    },
  );
  client = c;
  try {
    await c.start();
  } catch (err) {
    log(`the server did not start: ${err && err.message ? err.message : err}`);
    return;
  }
  reportServer(c, resolved);
}

async function restartClient(manifests) {
  const old = client;
  client = undefined;
  if (old) {
    try { await old.stop(); } catch (_) { /* already gone */ }
  }
  log('dawn.lspPath changed; restarting the server');
  await startClient(manifests);
}

function activate(context) {
  output = vscode.window.createOutputChannel('Dawn Language Server');
  context.subscriptions.push(output);

  const manifests = vscode.workspace.createFileSystemWatcher('**/{dawn.toml,dawn.lock}');
  context.subscriptions.push(manifests);

  context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration('dawn.lspPath')) restartClient(manifests);
  }));

  startClient(manifests);
  context.subscriptions.push({ dispose: () => client && client.stop() });
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
