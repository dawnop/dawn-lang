// server.js decides which file the extension starts and whether the server
// that answered is one it expects; both decisions were invisible when they
// went wrong (a stale `dawn` off PATH, a `dawn.lspPath` that named nothing).
// They are pure functions, so they run here under plain node, without VS
// Code, against a temporary directory standing in for PATH.
//
// The last check joins the server to the extension: serverInfo is built in
// selfhost/src/lsp/server.dawn, and if its name ever stops being "dawn" every
// user gets the stale-server warning, which no other test would notice.

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

console.log("server contract: ok");
