import { defineConfig } from 'vite'

// Build the editor as one self-contained ES module + one CSS file with stable
// names, so the Dawn site generator can vendor them into dist/assets and drop a
// <script type="module"> onto the Playground page. No hashing (the generator
// controls cache headers), no code-splitting (one page, one bundle).
//
// This is an app build with a script input, not library mode. Library mode with
// the `es` format leaves whitespace in place even with `build.minify` on (Vite
// documents this under build.minify), which shipped a 769 kB bundle; nothing
// imports this module, so library mode bought nothing. `src/main.ts` is the
// input rather than index.html because index.html is only the dev harness.
export default defineConfig({
  // Dev only: mirror the production same-origin routes to the local runner and
  // WebSocket gateway (neither service needs browser CORS access).
  server: {
    proxy: {
      '/api/run': { target: 'http://127.0.0.1:8087', rewrite: (p) => p.replace(/^\/api\/run/, '/run') },
      '/api/check': { target: 'http://127.0.0.1:8087', rewrite: (p) => p.replace(/^\/api\/check/, '/check') },
      '/api/health': { target: 'http://127.0.0.1:8087', rewrite: (p) => p.replace(/^\/api\/health/, '/health') },
      '/api/lsp': {
        target: 'ws://127.0.0.1:8088',
        ws: true,
        rewrite: (p) => p.replace(/^\/api\/lsp/, '/lsp'),
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Same-origin <script type="module"> on one page: nothing to preload, and
    // no polyfill should be injected into the bundle.
    modulePreload: false,
    rollupOptions: {
      input: 'src/main.ts',
      output: {
        format: 'es',
        entryFileNames: 'playground.js',
        assetFileNames: 'playground.[ext]',
        inlineDynamicImports: true,
      },
    },
  },
})
