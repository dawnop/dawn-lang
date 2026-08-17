// The extension grammar is executable editor behavior, so this contract loads
// the same TextMate engine and Oniguruma WASM as VS Code. Structural inventory
// checks supplement that behavior; they never replace real scope tokenization.

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vscodeOniguruma = require("vscode-oniguruma");
const vscodeTextmate = require("vscode-textmate");

const ROOT = path.resolve(__dirname, "../../..");
const GRAMMAR_PATH = path.join(__dirname, "../syntaxes/dawn.tmLanguage.json");
const CORPUS_PATH = path.join(__dirname, "scope-corpus.json");
const TOKEN_PATH = path.join(ROOT, "selfhost/src/front/token.dawn");
const LEXER_PATH = path.join(ROOT, "selfhost/src/front/lexer.dawn");
const CONTEXTUAL_KEYWORDS = ["opaque", "as", "derive", "handle"];
const REQUIRED_DEV_DEPENDENCIES = {
  "vscode-oniguruma": "2.0.1",
  "vscode-textmate": "9.3.2"
};

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function sorted(values) {
  return [...values].sort();
}

function hardKeywords() {
  const source = fs.readFileSync(TOKEN_PATH, "utf8");
  const start = source.indexOf("pub fn keyword(text: String)");
  assert.notEqual(start, -1, "compiler keyword table is missing");
  const end = source.indexOf("_ -> None", start);
  assert.notEqual(end, -1, "compiler keyword table has no fallback arm");
  const body = source.slice(start, end);
  const entries = [...body.matchAll(/^\s*"([^"]+)"\s*->\s*Some\(([A-Z_]+)\)\s*$/gm)];
  assert.ok(entries.length > 0, "compiler keyword table is empty");
  const words = entries.map(match => match[1]);
  assert.equal(new Set(words).size, words.length, "compiler keyword table contains duplicates");
  return words;
}

function compilerOperators() {
  const tokenSource = fs.readFileSync(TOKEN_PATH, "utf8");
  const typeStart = tokenSource.indexOf("pub type TokKind =");
  const typeEnd = tokenSource.indexOf("pub type Seg =", typeStart);
  assert.notEqual(typeStart, -1, "TokKind declaration is missing");
  assert.notEqual(typeEnd, -1, "TokKind declaration has no end anchor");
  const kinds = [...tokenSource.slice(typeStart, typeEnd).matchAll(/^\s*\|\s+([A-Z][A-Z0-9_]*)\s*$/gm)]
    .map(match => match[1]);
  const first = kinds.indexOf("DOTDOT");
  const last = kinds.indexOf("AT");
  assert.ok(first >= 0 && last >= first, "operator TokKind range is missing");
  const operatorKinds = kinds.slice(first, last + 1).filter(kind => kind !== "UNDERSCORE");

  const lexerSource = fs.readFileSync(LEXER_PATH, "utf8");
  const mappings = new Map();
  function add(kind, spelling) {
    if (!operatorKinds.includes(kind)) return;
    assert.ok(!mappings.has(kind), `compiler operator ${kind} has duplicate spellings`);
    mappings.set(kind, spelling);
  }

  // Each table entry says two things: which characters the dispatch tested for,
  // and which text the token carries. The spelling is what the lexer emits, so
  // that is what this reads; the characters are read as well, and the two have
  // to agree. They are not the same claim, and only the first one was here
  // while the tables answered a bare TokKind and the text was sliced out of the
  // source: an entry whose text is not its own source span would make `fmt`,
  // which reprints tokens from `.text`, print something the parser never read.
  function addTableEntry(kind, characters, spelling) {
    assert.equal(
      spelling,
      characters,
      `compiler operator ${kind} matches ${JSON.stringify(characters)} and ` +
      `emits ${JSON.stringify(spelling)}`
    );
    add(kind, spelling);
  }

  const twoStart = lexerSource.indexOf("fn two_kind(");
  const twoEnd = lexerSource.indexOf("fn one_kind(", twoStart);
  assert.notEqual(twoStart, -1, "two-character operator table is missing");
  assert.notEqual(twoEnd, -1, "two-character operator table has no end anchor");
  const twoBody = lexerSource.slice(twoStart, twoEnd);
  let twoEntries = 0;
  for (const match of twoBody.matchAll(
    /(?:if|else if) c == '(.)' && c1 == '(.)' \{ Some\(\(([A-Z]+), "([^"]*)"\)\) \}/g
  )) {
    addTableEntry(match[3], match[1] + match[2], match[4]);
    twoEntries += 1;
  }

  const oneStart = twoEnd;
  const oneEnd = lexerSource.indexOf("fn lex_symbol(", oneStart);
  assert.notEqual(oneEnd, -1, "one-character operator table has no end anchor");
  const oneBody = lexerSource.slice(oneStart, oneEnd);
  let oneEntries = 0;
  for (const match of oneBody.matchAll(
    /^\s*'(.)' -> Some\(\(([A-Z]+), "([^"]*)"\)\)\s*$/gm
  )) {
    addTableEntry(match[2], match[1], match[3]);
    oneEntries += 1;
  }

  // Both tables are read out of source text, so the shape they are written in
  // is this scraper's input. A table that matched nothing used to surface as
  // "every operator lacks a spelling" several assertions later, which is how a
  // batch that only rewrote the tables read as a broken grammar.
  assert.ok(twoEntries > 0, "the two-character operator table matched no entries");
  assert.ok(oneEntries > 0, "the one-character operator table matched no entries");

  const unsignedShift = lexerSource.match(/tok\(USHR,\s*"([^"]+)"/);
  assert.ok(unsignedShift, "USHR spelling is missing");
  add("USHR", unsignedShift[1]);

  const missing = operatorKinds.filter(kind => !mappings.has(kind));
  assert.deepEqual(missing, [], `operator TokKinds lack lexer spellings: ${missing.join(", ")}`);
  const lexemes = operatorKinds.map(kind => mappings.get(kind));
  assert.equal(new Set(lexemes).size, lexemes.length, "compiler operators contain duplicate spellings");
  return lexemes;
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function wordPattern(words) {
  return `(?<![_\\p{L}\\p{Nd}])(?:${words.map(escapeRegex).join("|")})(?![_\\p{L}\\p{Nd}])`;
}

function operatorPattern(operators) {
  return operators.map(escapeRegex).join("|");
}

async function loadWasm() {
  const bytes = fs.readFileSync(require.resolve("vscode-oniguruma/release/onig.wasm"));
  const wasm = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  await vscodeOniguruma.loadWASM(wasm);
}

async function loadGrammar(rawGrammar) {
  const onigLib = Promise.resolve({
    createOnigScanner: patterns => new vscodeOniguruma.OnigScanner(patterns),
    createOnigString: value => new vscodeOniguruma.OnigString(value)
  });
  const registry = new vscodeTextmate.Registry({
    onigLib,
    loadGrammar: async scopeName => {
      if (scopeName !== "source.dawn") return null;
      return vscodeTextmate.parseRawGrammar(JSON.stringify(rawGrammar), GRAMMAR_PATH);
    }
  });
  const grammar = await registry.loadGrammar("source.dawn");
  assert.ok(grammar, "TextMate did not load source.dawn");
  return grammar;
}

function tokenize(grammar, source) {
  const lines = source.split("\n");
  const tokenLines = [];
  let stack = vscodeTextmate.INITIAL;
  for (const line of lines) {
    const result = grammar.tokenizeLine(line, stack);
    tokenLines.push(result.tokens);
    stack = result.ruleStack;
  }
  return { lines, tokenLines };
}

function findSpan(line, expectation) {
  const occurrence = expectation.occurrence || 0;
  let start = -1;
  let from = 0;
  for (let index = 0; index <= occurrence; index += 1) {
    start = line.indexOf(expectation.text, from);
    assert.notEqual(
      start,
      -1,
      `corpus text ${JSON.stringify(expectation.text)} occurrence ${occurrence} is missing`
    );
    from = start + expectation.text.length;
  }
  return { start, end: start + expectation.text.length };
}

function scopesForSpan(tokens, span) {
  return tokens
    .filter(token => token.startIndex < span.end && token.endIndex > span.start)
    .flatMap(token => token.scopes);
}

function assertExpectation(testCase, tokenized, expectation) {
  const line = tokenized.lines[expectation.line];
  assert.notEqual(line, undefined, `${testCase.name}: line ${expectation.line} is missing`);
  const span = findSpan(line, expectation);
  const scopes = scopesForSpan(tokenized.tokenLines[expectation.line], span);
  assert.ok(
    scopes.includes(expectation.scope),
    `${testCase.name}: ${JSON.stringify(expectation.text)} lacks ${expectation.scope}; got ${scopes.join(", ")}`
  );
  const forbidden = [
    ...(expectation.notScopes || []),
    ...(expectation.notScope ? [expectation.notScope] : [])
  ];
  for (const scope of forbidden) {
    assert.ok(
      !scopes.includes(scope),
      `${testCase.name}: ${JSON.stringify(expectation.text)} unexpectedly has ${scope}`
    );
  }
}

function isHardKeywordScope(scope) {
  return scope.startsWith("keyword.") ||
    scope.startsWith("storage.modifier.") ||
    scope.startsWith("constant.language.");
}

function countNamedScope(value, scope) {
  if (Array.isArray(value)) return value.reduce((total, item) => total + countNamedScope(item, scope), 0);
  if (value === null || typeof value !== "object") return 0;
  let count = value.name === scope ? 1 : 0;
  for (const child of Object.values(value)) count += countNamedScope(child, scope);
  return count;
}

function verifyHardKeywordInventory(rawGrammar, compilerWords) {
  const inventory = rawGrammar["x-dawn-hard-keywords"];
  assert.ok(inventory && typeof inventory === "object", "hard keyword inventory is missing");
  const entries = Object.entries(inventory);
  const words = entries.flatMap(([, values]) => values);
  assert.equal(new Set(words).size, words.length, "hard keyword inventory contains duplicates");
  assert.deepEqual(sorted(words), sorted(compilerWords), "hard keyword inventory differs from compiler truth");

  const patterns = rawGrammar.repository.hardKeywords.patterns;
  assert.equal(patterns.length, entries.length, "hard keyword scopes and patterns must be one-to-one");
  for (const pattern of patterns) {
    const scopedWords = inventory[pattern.name];
    assert.ok(scopedWords, `hard keyword pattern ${pattern.name} has no inventory entry`);
    assert.equal(pattern.match, wordPattern(scopedWords), `${pattern.name} regex differs from its inventory`);
  }
}

function verifyContextualInventory(rawGrammar) {
  assert.deepEqual(
    rawGrammar["x-dawn-contextual-keywords"],
    CONTEXTUAL_KEYWORDS,
    "contextual keyword inventory must remain exact"
  );
  const patterns = rawGrammar.repository.contextualKeywords.patterns;
  const words = patterns.map(pattern => pattern["x-dawn-word"]);
  assert.ok(words.every(word => typeof word === "string"), "every contextual pattern needs x-dawn-word");
  assert.deepEqual(sorted(words), sorted(CONTEXTUAL_KEYWORDS), "contextual patterns differ from inventory");
  assert.equal(new Set(words).size, words.length, "contextual patterns contain duplicates");
  assert.equal(
    countNamedScope(rawGrammar, "keyword.contextual.dawn"),
    CONTEXTUAL_KEYWORDS.length,
    "contextual scope appears outside the exact inventory"
  );
}

function verifyOperatorInventory(rawGrammar, compilerLexemes) {
  const inventory = rawGrammar["x-dawn-operators"];
  assert.ok(Array.isArray(inventory), "operator inventory is missing");
  assert.equal(new Set(inventory).size, inventory.length, "operator inventory contains duplicates");
  assert.deepEqual(sorted(inventory), sorted(compilerLexemes), "operator inventory differs from compiler truth");
  const patterns = rawGrammar.repository.operators.patterns;
  assert.equal(patterns.length, 1, "operator inventory must drive one longest-first pattern");
  assert.equal(patterns[0].name, "keyword.operator.dawn", "operator scope changed");
  assert.equal(patterns[0].match, operatorPattern(inventory), "operator regex differs from its inventory");

  let prefixAssertions = 0;
  for (let shorterIndex = 0; shorterIndex < inventory.length; shorterIndex += 1) {
    const shorter = inventory[shorterIndex];
    for (let longerIndex = 0; longerIndex < inventory.length; longerIndex += 1) {
      const longer = inventory[longerIndex];
      if (longer.length > shorter.length && longer.startsWith(shorter)) {
        assert.ok(
          longerIndex < shorterIndex,
          `operator ${JSON.stringify(longer)} must precede its prefix ${JSON.stringify(shorter)}`
        );
        prefixAssertions += 1;
      }
    }
  }
  assert.ok(prefixAssertions > 0, "operator inventory has no prefix-overlap control cases");
  return prefixAssertions;
}

async function validate(rawGrammar) {
  const grammar = await loadGrammar(rawGrammar);
  const corpus = readJson(CORPUS_PATH);
  let assertions = 0;
  for (const testCase of corpus.cases) {
    const tokenized = tokenize(grammar, testCase.source);
    for (const expectation of testCase.expect) {
      assertExpectation(testCase, tokenized, expectation);
      assertions += 1;
    }
  }

  const keywords = hardKeywords();
  for (const keyword of keywords) {
    const tokenized = tokenize(grammar, keyword);
    const scopes = scopesForSpan(tokenized.tokenLines[0], { start: 0, end: keyword.length });
    assert.ok(
      scopes.some(isHardKeywordScope) && !scopes.includes("keyword.contextual.dawn"),
      `compiler hard keyword ${keyword} is not highlighted as a hard keyword: ${scopes.join(", ")}`
    );
    assertions += 1;
  }
  const javaTokens = tokenize(grammar, "java");
  const javaScopes = scopesForSpan(javaTokens.tokenLines[0], { start: 0, end: 4 });
  assert.ok(javaScopes.includes("keyword.declaration.dawn"), "java must remain a hard keyword");
  assertions += 1;

  const operators = compilerOperators();
  for (const operator of operators) {
    const tokenized = tokenize(grammar, operator);
    const scopes = scopesForSpan(tokenized.tokenLines[0], { start: 0, end: operator.length });
    assert.ok(
      scopes.includes("keyword.operator.dawn"),
      `compiler operator ${operator} is not highlighted as an operator: ${scopes.join(", ")}`
    );
    assertions += 1;
  }

  verifyHardKeywordInventory(rawGrammar, keywords);
  verifyContextualInventory(rawGrammar);
  assertions += verifyOperatorInventory(rawGrammar, operators);
  return {
    cases: corpus.cases.length,
    assertions,
    keywords: keywords.length,
    contextual: CONTEXTUAL_KEYWORDS.length,
    operators: operators.length
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function replaceStrings(value, before, after) {
  let replacements = 0;
  function visit(node) {
    if (Array.isArray(node)) {
      for (let index = 0; index < node.length; index += 1) {
        if (typeof node[index] === "string") {
          const changed = node[index].split(before).join(after);
          if (changed !== node[index]) replacements += 1;
          node[index] = changed;
        } else {
          visit(node[index]);
        }
      }
    } else if (node !== null && typeof node === "object") {
      for (const [key, child] of Object.entries(node)) {
        if (typeof child === "string") {
          const changed = child.split(before).join(after);
          if (changed !== child) replacements += 1;
          node[key] = changed;
        } else {
          visit(child);
        }
      }
    }
  }
  visit(value);
  return replacements;
}

async function negativeControls(grammar) {
  const controls = [
    ["hard keyword omission", candidate => {
      const pattern = candidate.repository.hardKeywords.patterns[1];
      const changed = pattern.match.replace("|effect", "");
      assert.notEqual(changed, pattern.match, "hard keyword omission mutation did not apply");
      pattern.match = changed;
    }],
    ["hard keyword addition", candidate => {
      const pattern = candidate.repository.hardKeywords.patterns[1];
      const changed = pattern.match.replace("|test)", "|test|bogus)");
      assert.notEqual(changed, pattern.match, "hard keyword addition mutation did not apply");
      pattern.match = changed;
    }],
    ["contextual keyword omission", candidate => {
      candidate.repository.contextualKeywords.patterns[1].match = "(?!)";
    }],
    ["contextual keyword addition", candidate => {
      candidate.repository.contextualKeywords.patterns.unshift({
        "x-dawn-word": "bogus",
        "name": "keyword.contextual.dawn",
        "match": wordPattern(["bogus"])
      });
    }],
    ["triple string", candidate => {
      candidate.repository.tripleStrings.begin = "(?!)";
    }],
    ["braced interpolation omission", candidate => {
      candidate.repository.bracedInterpolation.begin = "(?!)";
    }],
    ["interpolation comment boundary", candidate => {
      candidate.repository.bracedInterpolation.patterns = [
        { "include": "#interpolationBraces" },
        { "include": "$self" }
      ];
    }],
    ["parenthesized effect", candidate => {
      const pattern = candidate.repository.effects.patterns[0];
      const optional = "(?:\\s*\\|\\s*[_\\p{L}][_\\p{L}\\p{Nd}]*)*";
      const required = "(?:\\s*\\|\\s*[_\\p{L}][_\\p{L}\\p{Nd}]*)+";
      const changed = pattern.begin.replace(optional, required);
      assert.notEqual(changed, pattern.begin, "parenthesized effect mutation did not apply");
      pattern.begin = changed;
    }],
    ["identifier Nd boundary", candidate => {
      const replacements = replaceStrings(candidate, "\\p{Nd}", "\\p{N}");
      assert.ok(replacements > 0, "identifier category mutation did not apply");
    }],
    ["exponent number", candidate => {
      candidate.repository.numbers.patterns[2].match = "(?!)";
    }],
    ["operator omission", candidate => {
      const pattern = candidate.repository.operators.patterns[0];
      const changed = pattern.match.replace("|=|<", "|<");
      assert.notEqual(changed, pattern.match, "operator omission mutation did not apply");
      pattern.match = changed;
    }],
    ["operator longest-first", candidate => {
      const inventory = [...candidate["x-dawn-operators"]];
      const shorterIndex = inventory.indexOf(">");
      const longerIndex = inventory.indexOf(">>>");
      assert.ok(shorterIndex > longerIndex, "operator reorder mutation precondition changed");
      inventory.splice(shorterIndex, 1);
      inventory.splice(inventory.indexOf(">>>"), 0, ">");
      candidate["x-dawn-operators"] = inventory;
      candidate.repository.operators.patterns[0].match = operatorPattern(inventory);
    }]
  ];
  for (const [name, mutate] of controls) {
    const candidate = clone(grammar);
    mutate(candidate);
    let rejected = false;
    try {
      await validate(candidate);
    } catch (_error) {
      rejected = true;
    }
    assert.ok(rejected, `${name} negative control unexpectedly stayed green`);
  }
  return controls.map(([name]) => name);
}

// Two separate claims, kept separate on purpose.
//
// Every devDependency is pinned to an exact version and the lock agrees. This
// runs over whatever is declared rather than over a fixed list: a caret range
// on a package added next year is the same hazard as a caret range on the two
// below, and a closed list says nothing about it while reddening merely because
// something was added. That is what it did until @vscode/vsce arrived to make
// the extension packageable, and the failure named exact versions while the
// actual complaint was about the size of the set.
//
// And the two packages this file itself loads stay at the versions the recorded
// scope results were measured against, because a tokenizer upgrade that moves
// them is a result nobody re-measured.
function verifyDependencyPins() {
  const packageJson = readJson(path.join(__dirname, "../package.json"));
  const packageLock = readJson(path.join(__dirname, "../package-lock.json"));
  const declared = packageJson.devDependencies;
  const locked = packageLock.packages[""].devDependencies;
  for (const [dependency, version] of Object.entries(declared)) {
    assert.match(
      version,
      /^\d+\.\d+\.\d+$/,
      `${dependency} devDependency must be an exact version, not ${version}`
    );
    assert.equal(
      locked[dependency],
      version,
      `package lock must preserve the ${dependency} pin`
    );
    assert.equal(
      packageLock.packages[`node_modules/${dependency}`].version,
      version,
      `${dependency} lock entry must match its exact package pin`
    );
  }
  for (const [dependency, version] of Object.entries(REQUIRED_DEV_DEPENDENCIES)) {
    assert.equal(
      declared[dependency],
      version,
      `${dependency} is what this contract tokenizes with; it must stay at ${version}`
    );
  }
}

async function main() {
  verifyDependencyPins();
  await loadWasm();
  const rawGrammar = readJson(GRAMMAR_PATH);
  const result = await validate(rawGrammar);
  const controls = await negativeControls(rawGrammar);
  process.stdout.write(`TextMate scope contract: ${result.cases} cases, ${result.assertions} assertions\n`);
  process.stdout.write(
    `TextMate inventories: ${result.keywords} hard keywords, ${result.contextual} contextual keywords, ` +
    `${result.operators} operators\n`
  );
  process.stdout.write(`TextMate negative controls rejected: ${controls.join(", ")}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
