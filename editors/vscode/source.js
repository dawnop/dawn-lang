// A library URI belongs to the running server's immutable source snapshot.
// Fetch through that server so navigation and analysis always read the same
// text, including when no standard-library files exist on the client.
const scheme = 'dawn-stdlib';

function register(vscode, context, currentClient) {
  const provider = {
    async provideTextDocumentContent(uri, token) {
      const client = currentClient();
      if (!client) throw new Error('The Dawn language server is not running');
      const result = await client.sendRequest('dawn/source', { uri: uri.toString() }, token);
      if (!result || result.uri !== uri.toString() || result.languageId !== 'dawn'
          || typeof result.text !== 'string') {
        throw new Error('Invalid Dawn library source response');
      }
      return result.text;
    },
  };
  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider(scheme, provider));
  return provider;
}

// LanguageClient features contribute capabilities during initialize. This
// feature is registered before start, together with the content provider.
function capability() {
  return {
    fillClientCapabilities(capabilities) {
      capabilities.experimental = { ...capabilities.experimental, dawnSource: true };
    },
    initialize() {},
    clear() {},
    getState() { return { kind: 'static' }; },
  };
}

module.exports = { scheme, register, capability };
