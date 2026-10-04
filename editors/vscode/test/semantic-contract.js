// The server's semantic tokens legend lives in selfhost/src/lsp/lsptok.dawn
// and the extension's half of it lives in package.json, and nothing but this
// test joins the two. vscode-languageclient decodes tokens against whatever
// legend the server sends, so the extension never holds indices; what it does
// hold is the declarations VS Code needs for any name outside LSP's standard
// list, and the TextMate scopes a theme without semantic rules falls back to.
// A modifier the server sends and the manifest does not declare is dropped by
// VS Code without a word, and a scope selector naming a type or modifier the
// legend does not have colours nothing; both stay green in every other test.
//
// The checks are pure functions over (manifest, legend), so each one has a
// mutant below that has to turn it red before the real inputs are trusted.

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../../..");
const MANIFEST_PATH = path.join(__dirname, "../package.json");
const CHANGELOG_PATH = path.join(__dirname, "../CHANGELOG.md");
const LEGEND_PATH = path.join(ROOT, "selfhost/src/lsp/lsptok.dawn");

// LSP 3.17 SemanticTokenTypes and SemanticTokenModifiers: the names VS Code
// knows without a declaration and has default TextMate fallbacks for.
const STANDARD_TYPES = new Set([
  "namespace", "type", "class", "enum", "interface", "struct", "typeParameter",
  "parameter", "variable", "property", "enumMember", "event", "function", "method",
  "macro", "keyword", "modifier", "comment", "string", "number", "regexp", "operator",
  "decorator"
]);
const STANDARD_MODIFIERS = new Set([
  "declaration", "definition", "readonly", "static", "deprecated", "abstract", "async",
  "modification", "documentation", "defaultLibrary"
]);

class ContractError extends Error {
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.code = code;
  }
}

function fail(code, detail) {
  throw new ContractError(code, detail);
}

// `pub(pkg) fn token_types() -> List[String] = [ "a", "b" ]`, possibly over
// several lines; the list literal is the function's whole body.
function legendList(source, name) {
  const match = new RegExp(`fn ${name}\\(\\) -> List\\[String\\] =\\s*\\[([^\\]]*)\\]`).exec(source);
  if (!match) fail("LEGEND_NOT_FOUND", name);
  return [...match[1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);
}

function readLegend() {
  const source = fs.readFileSync(LEGEND_PATH, "utf8");
  return { types: legendList(source, "token_types"), modifiers: legendList(source, "token_modifiers") };
}

function checkDeclarations(manifest, legend) {
  const contributes = manifest.contributes || {};
  const declaredTypes = (contributes.semanticTokenTypes || []).map((entry) => entry.id);
  const declaredModifiers = (contributes.semanticTokenModifiers || []).map((entry) => entry.id);
  for (const type of legend.types) {
    if (!STANDARD_TYPES.has(type) && !declaredTypes.includes(type)) {
      fail("TYPE_NOT_DECLARED", type);
    }
  }
  for (const modifier of legend.modifiers) {
    if (!STANDARD_MODIFIERS.has(modifier) && !declaredModifiers.includes(modifier)) {
      fail("MODIFIER_NOT_DECLARED", modifier);
    }
  }
  for (const type of declaredTypes) {
    if (!legend.types.includes(type)) fail("STALE_TYPE_DECLARATION", type);
  }
  for (const modifier of declaredModifiers) {
    if (!legend.modifiers.includes(modifier)) fail("STALE_MODIFIER_DECLARATION", modifier);
    const entry = contributes.semanticTokenModifiers.find((item) => item.id === modifier);
    if (typeof entry.description !== "string" || entry.description.length === 0) {
      fail("MODIFIER_WITHOUT_DESCRIPTION", modifier);
    }
  }
}

// A selector is `type(.modifier)*` or `*.modifier...`, in the manifest's own
// `language` block. Every non-standard name needs one, because VS Code has no
// default fallback scope for a name it did not define.
function checkScopes(manifest, legend) {
  const blocks = (manifest.contributes || {}).semanticTokenScopes || [];
  const covered = new Set();
  for (const block of blocks) {
    if (block.language !== "dawn") fail("SCOPES_NOT_FOR_DAWN", JSON.stringify(block.language));
    for (const [selector, scopes] of Object.entries(block.scopes || {})) {
      const [type, ...modifiers] = selector.split(".");
      if (type !== "*" && !legend.types.includes(type)) fail("SELECTOR_UNKNOWN_TYPE", selector);
      for (const modifier of modifiers) {
        if (!legend.modifiers.includes(modifier)) fail("SELECTOR_UNKNOWN_MODIFIER", selector);
        covered.add(modifier);
      }
      if (type !== "*") covered.add(type);
      if (!Array.isArray(scopes) || scopes.length === 0 || !scopes.every((s) => typeof s === "string" && s)) {
        fail("SELECTOR_WITHOUT_SCOPE", selector);
      }
    }
  }
  for (const name of [...legend.types, ...legend.modifiers]) {
    if (!STANDARD_TYPES.has(name) && !STANDARD_MODIFIERS.has(name) && !covered.has(name)) {
      fail("CUSTOM_NAME_WITHOUT_SCOPE", name);
    }
  }
}

function checkChangelog(manifest, changelog) {
  const first = /^## (\S+)/m.exec(changelog);
  if (!first || first[1] !== manifest.version) {
    fail("CHANGELOG_NOT_AT_VERSION", `${first && first[1]} vs ${manifest.version}`);
  }
}

function checkAll(manifest, legend, changelog) {
  checkDeclarations(manifest, legend);
  checkScopes(manifest, legend);
  checkChangelog(manifest, changelog);
}

function expectRed(label, code, run) {
  try {
    run();
  } catch (error) {
    if (error instanceof ContractError && error.code === code) {
      console.log(`  ok  mutant turns red: ${label}`);
      return;
    }
    throw error;
  }
  assert.fail(`mutant stayed green: ${label}`);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf8"));
const legend = readLegend();
const changelog = fs.readFileSync(CHANGELOG_PATH, "utf8");

assert.ok(legend.types.length > 0 && legend.modifiers.length > 0, "the legend was read");

expectRed("the server adds a modifier the manifest does not declare", "MODIFIER_NOT_DECLARED", () => {
  checkAll(manifest, { ...legend, modifiers: [...legend.modifiers, "effect"] }, changelog);
});
expectRed("the server adds a type the manifest does not declare", "TYPE_NOT_DECLARED", () => {
  checkAll(manifest, { ...legend, types: [...legend.types, "effect"] }, changelog);
});
expectRed("the declaration of mutable is dropped", "MODIFIER_NOT_DECLARED", () => {
  const mutant = clone(manifest);
  mutant.contributes.semanticTokenModifiers = [];
  checkAll(mutant, legend, changelog);
});
expectRed("the server drops a modifier the manifest still declares", "STALE_MODIFIER_DECLARATION", () => {
  checkAll(manifest, { ...legend, modifiers: legend.modifiers.filter((m) => STANDARD_MODIFIERS.has(m)) }, changelog);
});
expectRed("a selector names a modifier the legend lacks", "SELECTOR_UNKNOWN_MODIFIER", () => {
  const mutant = clone(manifest);
  mutant.contributes.semanticTokenScopes[0].scopes = { "*.mutabel": ["markup.underline"] };
  checkAll(mutant, legend, changelog);
});
expectRed("mutable has no fallback scope", "CUSTOM_NAME_WITHOUT_SCOPE", () => {
  const mutant = clone(manifest);
  mutant.contributes.semanticTokenScopes[0].scopes = {};
  checkAll(mutant, legend, changelog);
});
expectRed("the version moves without a changelog entry", "CHANGELOG_NOT_AT_VERSION", () => {
  checkAll({ ...manifest, version: "9.9.9" }, legend, changelog);
});

checkAll(manifest, legend, changelog);
console.log(`  ok  legend (${legend.types.length} types, ${legend.modifiers.length} modifiers) matches the manifest's declarations and scopes`);
