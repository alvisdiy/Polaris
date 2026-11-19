import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    globals: true,
  },
  root: 'src',
  publicDir: '../public',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      // Only the versioned API is proxied. A bare '/api' also matched the
      // frontend's own module requests (/api/composables.ts), which Vite then
      // forwarded to the backend and got a 404 for — the dev build rendered an
      // empty <main> while the production build worked, because bundling
      // removes those requests entirely.
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
