import { defineConfig } from 'vite'

// Build the editor as one self-contained ES module + one CSS file with stable
// names, so the Dawn site generator can vendor them into dist/assets and drop a
// <script type="module"> onto the Playground page. No hashing (the generator
// controls cache headers), no code-splitting (one page, one bundle).
export default defineConfig({
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
