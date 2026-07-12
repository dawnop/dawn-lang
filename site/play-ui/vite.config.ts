import { defineConfig } from 'vite'

// Build the editor as one self-contained ES module + one CSS file with stable
// names, so the Dawn site generator can vendor them into dist/assets and drop a
// <script type="module"> onto the Playground page. No hashing (the generator
// controls cache headers), no code-splitting (one page, one bundle).
export default defineConfig({
  // Dev only: proxy /api/run to the local runner, mirroring the production nginx
  // setup so the dev harness stays same-origin (no CORS on the runner needed).
  server: {
    proxy: {
      '/api/run': { target: 'http://127.0.0.1:8087', rewrite: (p) => p.replace(/^\/api\/run/, '/run') },
      '/api/check': { target: 'http://127.0.0.1:8087', rewrite: (p) => p.replace(/^\/api\/check/, '/check') },
      '/api/health': { target: 'http://127.0.0.1:8087', rewrite: (p) => p.replace(/^\/api\/health/, '/health') },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    lib: {
      entry: 'src/main.ts',
      formats: ['es'],
      fileName: () => 'playground.js',
    },
    rollupOptions: {
      output: {
        assetFileNames: 'playground.[ext]',
      },
    },
  },
})
