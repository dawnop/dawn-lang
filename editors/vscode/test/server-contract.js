// server.js decides which file the extension starts and whether the server
// that answered is one it expects; both decisions were invisible when they
// went wrong (a stale `dawn` off PATH, a `dawn.lspPath` that named nothing).
// They are pure functions, so they run here under plain node, without VS
// Code, against a temporary directory standing in for PATH.
//
// The last check joins the server to the extension: serverInfo is built in
// selfhost/src/lsp/server.dawn, and if its name ever stops being "dawn" every
// user gets the stale-server warning, which no other test would notice.
// The inlay hint settings are joined the same way: each key must be one
// `inlay_opts_of` reads, and its default in package.json must be the
// server's `default_inlay_opts`, or the setting would show a default the
// server does not have.

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const s = require("../server");

const ROOT = path.resolve(__dirname, "../../..");

// expandCommand
assert.equal(s.expandCommand("dawn", { home: "/h" }), "dawn");
assert.equal(s.expandCommand("", { home: "/h" }), "dawn");
assert.equal(s.expandCommand("  ", { home: "/h" }), "dawn");
assert.equal(s.expandCommand("~/bin/dawn", { home: "/h" }), "/h/bin/dawn");
assert.equal(s.expandCommand("${userHome}/bin/dawn", { home: "/h" }), "/h/bin/dawn");
assert.equal(
  s.expandCommand("${workspaceFolder}/bin/dawn", { home: "/h", workspaceFolder: "/w" }),
  "/w/bin/dawn",
);
assert.equal(s.expandCommand("bin/dawn", { home: "/h", workspaceFolder: "/w" }), "/w/bin/dawn");
assert.equal(s.expandCommand("./bin/dawn", { home: "/h", workspaceFolder: "/w" }), "/w/bin/dawn");
assert.equal(s.expandCommand("/abs/dawn", { home: "/h", workspaceFolder: "/w" }), "/abs/dawn");
// No folder open: a relative path is left as written, not resolved against
// the extension host's cwd.
assert.equal(s.expandCommand("bin/dawn", { home: "/h" }), "bin/dawn");

// findExecutable, against a scratch PATH
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dawn-vscode-"));
try {
  const a = path.join(tmp, "a");
  const b = path.join(tmp, "b");
  fs.mkdirSync(a);
  fs.mkdirSync(b);
  const plain = path.join(a, "dawn");
  fs.writeFileSync(plain, "#!/bin/sh\n");
  fs.chmodSync(plain, 0o644);
  const exe = path.join(b, "dawn");
  fs.writeFileSync(exe, "#!/bin/sh\n");
  fs.chmodSync(exe, 0o755);
  const env = { PATH: [path.join(tmp, "missing"), a, b].join(":") };
  if (process.platform !== "win32") {
    // A non-executable file earlier on PATH is skipped, as the shell does.
    assert.equal(s.findExecutable("dawn", env, "linux"), exe);
    assert.equal(s.findExecutable(plain, env, "linux"), null);
  }
  assert.equal(s.findExecutable(exe, env, process.platform), exe);
  assert.equal(s.findExecutable("nope", env, process.platform), null);
  assert.equal(s.findExecutable(path.join(tmp, "nope"), env, process.platform), null);
  // A directory with the right name is not the server.
  fs.mkdirSync(path.join(tmp, "c"));
  fs.mkdirSync(path.join(tmp, "c", "dawn"));
  assert.equal(s.findExecutable("dawn", { PATH: path.join(tmp, "c") }, process.platform), null);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}

// settingSource: the most specific layer with a value wins
assert.equal(s.settingSource(undefined), "default");
assert.equal(s.settingSource({ defaultValue: "dawn" }), "default");
assert.equal(s.settingSource({ defaultValue: "dawn", globalValue: "/x" }), "user setting");
assert.equal(
  s.settingSource({ globalValue: "/x", workspaceValue: "/y" }),
  "workspace setting",
);
assert.equal(
  s.settingSource({ globalValue: "/x", workspaceValue: "/y", workspaceFolderValue: "/z" }),
  "workspace folder setting",
);

// compareVersions
assert.equal(s.compareVersions("0.83.0", "0.83.0"), 0);
assert.equal(s.compareVersions("0.77.0", "0.83.0"), -1);
assert.equal(s.compareVersions("0.100.0", "0.83.0"), 1);
assert.equal(s.compareVersions("1.0", "0.99.9"), 1);
assert.equal(s.compareVersions("0.83", "0.83.0"), 0);

// serverInfoProblem
assert.equal(s.serverInfoProblem({ name: "dawn", version: s.MIN_SERVER_VERSION }), null);
assert.equal(s.serverInfoProblem({ name: "dawn", version: "9.0.0" }), null);
assert.match(s.serverInfoProblem(undefined), /did not report its version/);
assert.match(s.serverInfoProblem(null), /did not report its version/);
assert.match(s.serverInfoProblem({ name: "other", version: "1.0.0" }), /not "dawn"/);
assert.match(s.serverInfoProblem({ name: "dawn" }), /no version string/);
assert.match(s.serverInfoProblem({ name: "dawn", version: "0.1.0" }), /older than/);

// The server's half: the name it sends is the one checked for above.
const serverSrc = fs.readFileSync(path.join(ROOT, "selfhost/src/lsp/server.dawn"), "utf8");
const m = serverSrc.match(/fn server_info\(\) -> Json =\s*\n\s*jobj\(\[\("name", JStr\("([^"]*)"\)\)/);
assert.ok(m, "server_info() not found in selfhost/src/lsp/server.dawn");
assert.equal(s.serverInfoProblem({ name: m[1], version: s.MIN_SERVER_VERSION }), null);

// initializationOptions: booleans pass through, anything else is left out
const all = (v) => s.initializationOptions(() => v);
assert.deepEqual(all(true), {
  inlayHints: { propagatedErrors: true, declarationEffects: true, patternTypes: true },
});
assert.deepEqual(all(false), {
  inlayHints: { propagatedErrors: false, declarationEffects: false, patternTypes: false },
});
assert.deepEqual(all("yes"), { inlayHints: {} });
assert.deepEqual(s.initializationOptions((_, dflt) => dflt), {
  inlayHints: { propagatedErrors: false, declarationEffects: true, patternTypes: true },
});

// The server's half of the inlay hint settings.
const inlaySrc = fs.readFileSync(path.join(ROOT, "selfhost/src/lsp/lspinlay.dawn"), "utf8");
const optsOf = serverSrc.match(/fn inlay_opts_of\(params: Json\) -> InlayOpts = \{([\s\S]*?)\n\}/);
assert.ok(optsOf, "inlay_opts_of not found in selfhost/src/lsp/server.dawn");
const dflts = inlaySrc.match(/fn default_inlay_opts\(\) -> InlayOpts =\s*InlayOpts \{([\s\S]*?)\}/);
assert.ok(dflts, "default_inlay_opts not found in selfhost/src/lsp/lspinlay.dawn");
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "../package.json"), "utf8"));
const props = manifest.contributes.configuration.properties;
for (const { key, default: dflt } of s.INLAY_HINT_SETTINGS) {
  const read = optsOf[1].match(new RegExp(`(\\w+) = json_flag\\(j, "${key}", d\\.\\1\\)`));
  assert.ok(read, `the server does not read inlayHints.${key}`);
  const field = dflts[1].match(new RegExp(`\\b${read[1]} = (true|false)`));
  assert.ok(field, `default_inlay_opts has no ${read[1]}`);
  assert.equal(dflt, field[1] === "true", `default of ${key}`);
  const prop = props[`dawn.inlayHints.${key}`];
  assert.ok(prop, `package.json does not declare dawn.inlayHints.${key}`);
  assert.equal(prop.type, "boolean");
  assert.equal(prop.default, dflt, `package.json default of dawn.inlayHints.${key}`);
}
const declared = Object.keys(props).filter((k) => k.startsWith("dawn.inlayHints."));
assert.deepEqual(
  declared.sort(),
  s.INLAY_HINT_SETTINGS.map((x) => `dawn.inlayHints.${x.key}`).sort(),
  "package.json declares an inlay hint setting the extension does not pass",
);

console.log("server contract: ok");


// Load the real extension with a client double: settings changes must stop the
// old client before starting the next one with the new executable and argv.
async function launchContract() {
  const vm = require("node:vm");
  const { spawnSync } = require("node:child_process");
  const clients = [];
  const events = [];
  const lines = [];
  const settings = { lspPath: "dawn", lspArgs: [] };
  let changed;
  let execute = false;
  let fail = false;
  class Client {
    constructor(id, name, launch) {
      this.launch = launch;
      this.index = clients.length;
      this.initializeResult = { serverInfo: { name: "dawn", version: "1.0.0" } };
      clients.push(this);
    }
    registerFeature() {}
    async start() {
      events.push(`start ${this.index}`);
      if (fail) throw new Error("capability refused");
      if (execute) {
        this.child = spawnSync(this.launch.command, this.launch.args, {
          ...this.launch.options, encoding: "utf8",
        });
        assert.equal(this.child.status, 0, this.child.stderr);
      }
    }
    async stop() { events.push(`stop ${this.index}`); }
  }
  const vscode = {
    workspace: {
      workspaceFolders: [{ uri: { fsPath: "/workspace" } }],
      getConfiguration() {
        return {
          get: (key, dflt) => settings[key] === undefined ? dflt : settings[key],
          inspect: () => ({ workspaceValue: true }),
        };
      },
      createFileSystemWatcher: () => ({ dispose() {} }),
      onDidChangeConfiguration(fn) { changed = fn; return { dispose() {} }; },
    },
    window: { createOutputChannel: () => ({ appendLine: (line) => lines.push(line) }) },
  };
  const module = { exports: {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../extension.js"), "utf8"), {
    module, process,
    require: (name) => {
      if (name === "vscode") return vscode;
      if (name === "vscode-languageclient/node") return { LanguageClient: Client };
      if (name === "./server") return s;
      if (name === "./source") return { register() {}, capability() {}, scheme: "dawn-stdlib" };
      return require(name);
    },
  }, { filename: "extension.js" });
  const settled = () => new Promise((resolve) => setImmediate(resolve));
  const change = async (...keys) => {
    changed({ affectsConfiguration: (key) => keys.includes(key) });
    await settled();
  };
  const argv = (client) => Array.from(client.launch.args);
  module.exports.activate({ subscriptions: [] });
  await settled();
  assert.equal(path.basename(clients[0].launch.command), process.platform === "win32" ? "dawn.exe" : "dawn");
  assert.deepEqual(argv(clients[0]), ["lsp"]);
  assert.equal(clients[0].launch.options.shell, false);

  settings.lspPath = process.execPath;
  await change("dawn.lspPath");
  assert.equal(clients[1].launch.command, fs.realpathSync(process.execPath));
  assert.deepEqual(events, ["start 0", "stop 0", "start 1"]);

  // A real child receives empty, spaced, Unicode and shell-looking arguments
  // byte for byte. A shell would expand these or create the marker file.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dawn-launch-"));
  try {
    const marker = path.join(dir, "expanded");
    const opaque = ["", "/a path/\u96ea.jar", "\"quoted\"", "$HOME", "${workspaceFolder}",
      `$(touch '${marker}')`, "`touch ignored`", "a;b", "*"];
    settings.lspArgs = ["-e", "process.stdout.write(JSON.stringify(process.argv.slice(1)))", "--", ...opaque];
    execute = true;
    await change("dawn.lspArgs");
    execute = false;
    assert.equal(clients.length, 3);
    assert.deepEqual(JSON.parse(clients[2].child.stdout), [...opaque, "lsp"]);
    assert.deepEqual(argv(clients[2]), [...settings.lspArgs, "lsp"]);
    assert.equal(clients[2].launch.options.shell, false);
    assert.equal(fs.existsSync(marker), false);
    assert.deepEqual(events.slice(-2), ["stop 1", "start 2"]);
    assert.ok(lines.some((line) => line.includes(`argv = ${JSON.stringify([...settings.lspArgs, "lsp"])}`)));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  await change("unrelated");
  assert.equal(clients.length, 3);

  settings.lspPath = "java";
  settings.lspArgs = ["-Xss512m", "-jar", "/absolute/versioned/dawn-selfhost.jar"];
  await change("dawn.lspPath", "dawn.lspArgs");
  assert.equal(clients.length, 4, "one restart when both settings change");
  assert.deepEqual(argv(clients[3]), [...settings.lspArgs, "lsp"]);
  assert.equal(path.basename(clients[3].launch.command), process.platform === "win32" ? "java.exe" : "java");

  fail = true;
  settings.lspPath = "dawn";
  settings.lspArgs = [];
  await change("dawn.lspPath", "dawn.lspArgs");
  assert.equal(clients.length, 5, "a failed native start does not select another toolchain");
  assert.deepEqual(argv(clients[4]), ["lsp"]);
  assert.ok(lines.some((line) => line.includes("capability refused")));
  assert.ok(lines.some((line) => line.includes('dawn.lspArgs = ["-Xss512m","-jar"')));
  await module.exports.deactivate();
  assert.equal(events.at(-1), "stop 4");
  console.log("launch and restart contract: ok");
}

assert.equal(props["dawn.lspPath"].default, "dawn");
assert.equal(props["dawn.lspArgs"].type, "array");
assert.deepEqual(props["dawn.lspArgs"].items, { type: "string" });
assert.deepEqual(props["dawn.lspArgs"].default, []);
launchContract().catch((err) => { console.error(err); process.exitCode = 1; });
