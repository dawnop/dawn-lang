// Exercise the production provider with the same capability and request used
// by the server, including cancellation and stale-server failures.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const source = require('../source');

(async () => {
  let registered;
  let active;
  let disposed = false;
  const context = { subscriptions: [] };
  const vscode = { workspace: {
    registerTextDocumentContentProvider(scheme, provider) {
      assert.strictEqual(scheme, 'dawn-stdlib');
      registered = provider;
      return { dispose() { disposed = true; } };
    },
  } };
  source.register(vscode, context, () => active);
  const uri = { toString: () => 'dawn-stdlib:0123/std/math.dawn' };
  const token = {};
  await assert.rejects(() => registered.provideTextDocumentContent(uri, token), /not running/);
  active = { async sendRequest(method, params, cancellation) {
    assert.strictEqual(method, 'dawn/source');
    assert.deepStrictEqual(params, { uri: uri.toString() });
    assert.strictEqual(cancellation, token);
    return { uri: uri.toString(), languageId: 'dawn', text: '# 中文🎈\npub fn exp() = 1\n' };
  } };
  assert.strictEqual(await registered.provideTextDocumentContent(uri, token), '# 中文🎈\npub fn exp() = 1\n');
  active = { async sendRequest() { return { uri: 'wrong', languageId: 'dawn', text: '' }; } };
  await assert.rejects(() => registered.provideTextDocumentContent(uri, token), /Invalid/);
  active = { async sendRequest() { throw new Error('unknown library source document'); } };
  await assert.rejects(() => registered.provideTextDocumentContent(uri, token), /unknown/);
  const capabilities = { experimental: { existing: true } };
  source.capability().fillClientCapabilities(capabilities);
  assert.deepStrictEqual(capabilities.experimental, { existing: true, dawnSource: true });
  const extension = fs.readFileSync(path.join(__dirname, '../extension.js'), 'utf8');
  assert(extension.includes('c.registerFeature(source.capability())'));
  assert(extension.includes("{ scheme: source.scheme, language: 'dawn' }"));
  assert(extension.includes('source.register(vscode, context, () => client)'));
  context.subscriptions[0].dispose();
  assert(disposed);
  console.log('PASS virtual source provider and capability');
})().catch((err) => { console.error(err); process.exitCode = 1; });
