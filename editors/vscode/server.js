// Which `dawn` the extension runs, and whether the one that answered looks
// right. Kept apart from extension.js, with no `vscode` import, so that
// test/server-contract.js can run it under plain node in CI.
//
// It exists because of a 2026-10-04 session in which the editor showed
// hundreds of errors against a tree that checked clean: the server was a
// months-old `dawn` found on PATH, `dawn.lspPath` had not taken effect, and
// nothing on screen said which executable was running. Which of the
// following made the setting not apply that day is not known; each of them
// fails the same silent way, and each has a counterpart here:
//
// - the setting was read once, at activation, so an edit did nothing until
//   the window was reloaded (extension.js now restarts the client on change);
// - spawn does no shell expansion, so `~/...` or `${workspaceFolder}/...`
//   named a file that does not exist, and a relative path resolved against
//   the extension host's cwd rather than the workspace (expandCommand);
// - the value can sit in four layers (default, user, workspace, folder), and
//   a value set in one the window does not read looks exactly like a value
//   that was ignored (settingSource names the layer that won).
//
// The PATH lookup is done here rather than left to spawn so the output
// channel can print the file that will run, symlinks resolved: `dawn` on PATH
// was a link into a stale checkout, and only the resolved path says so.

"use strict";

const fs = require("node:fs");
const path = require("node:path");

// The oldest server version this extension accepts. serverInfo arrived after
// the 0.83.0 release, and a build between releases still reports the last
// one, so for now the field's presence is the real test; the floor is here
// for the day a later extension needs a later server.
const MIN_SERVER_VERSION = "0.83.0";

function hasSeparator(p) {
  return p.includes("/") || p.includes("\\");
}

// The command as spawn should see it, from the raw setting. `~` and the two
// variables a user is likely to try are expanded; a relative path that names
// a directory is resolved against the first workspace folder. A bare name
// (`dawn`) is left for the PATH lookup.
function expandCommand(raw, ctx) {
  let cmd = String(raw == null ? "" : raw).trim();
  if (cmd === "") cmd = "dawn";
  const home = ctx.home || "";
  const folder = ctx.workspaceFolder || "";
  if (home && (cmd === "~" || cmd.startsWith("~/") || cmd.startsWith("~\\"))) {
    cmd = home + cmd.slice(1);
  }
  cmd = cmd.split("${userHome}").join(home);
  if (folder) cmd = cmd.split("${workspaceFolder}").join(folder);
  if (hasSeparator(cmd) && !path.isAbsolute(cmd) && folder) {
    cmd = path.resolve(folder, cmd);
  }
  return cmd;
}

function isExecutableFile(p, fsImpl, platform) {
  try {
    const st = fsImpl.statSync(p);
    if (!st.isFile()) return false;
    if (platform !== "win32") fsImpl.accessSync(p, fs.constants.X_OK);
    return true;
  } catch (_) {
    return false;
  }
}

// The file spawn would run for `cmd`, or null when there is none. Mirrors the
// platform's lookup: a command with a separator is taken as a path, a bare
// name is searched for on PATH (with PATHEXT on Windows).
function findExecutable(cmd, env, platform, fsImpl) {
  fsImpl = fsImpl || fs;
  const exts = platform === "win32"
    ? [""].concat(String(env.PATHEXT || ".EXE;.CMD;.BAT;.COM").split(";").filter(Boolean))
    : [""];
  const tryAll = (base) => {
    for (const ext of exts) {
      if (isExecutableFile(base + ext, fsImpl, platform)) return base + ext;
    }
    return null;
  };
  if (hasSeparator(cmd)) return tryAll(cmd);
  const delim = platform === "win32" ? ";" : ":";
  const pathVar = env.PATH || env.Path || "";
  for (const dir of pathVar.split(delim)) {
    if (!dir) continue;
    const hit = tryAll(path.join(dir, cmd));
    if (hit) return hit;
  }
  return null;
}

// Which settings layer the effective value of `dawn.lspPath` came from, from
// `WorkspaceConfiguration.inspect`. The most specific layer that has a value
// wins, as it does in VS Code.
function settingSource(inspected) {
  if (!inspected) return "default";
  if (inspected.workspaceFolderValue !== undefined) return "workspace folder setting";
  if (inspected.workspaceValue !== undefined) return "workspace setting";
  if (inspected.globalValue !== undefined) return "user setting";
  return "default";
}

// Dotted numeric versions; a missing or non-numeric part counts as 0.
function compareVersions(a, b) {
  const pa = String(a).split(/[.+-]/).map((x) => parseInt(x, 10) || 0);
  const pb = String(b).split(/[.+-]/).map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

// null when the `serverInfo` of an initialize result is what this extension
// expects, otherwise one sentence saying what is wrong with it.
function serverInfoProblem(info, min) {
  min = min || MIN_SERVER_VERSION;
  if (!info || typeof info !== "object") {
    return "the server did not report its version; no release up to 0.83.0 does, so it is likely stale";
  }
  if (info.name !== "dawn") {
    return `the server calls itself ${JSON.stringify(info.name)}, not "dawn"`;
  }
  if (typeof info.version !== "string") {
    return "the server reported no version string";
  }
  if (compareVersions(info.version, min) < 0) {
    return `the server is dawn ${info.version}, older than ${min}`;
  }
  return null;
}

module.exports = {
  MIN_SERVER_VERSION,
  expandCommand,
  findExecutable,
  settingSource,
  compareVersions,
  serverInfoProblem,
};
