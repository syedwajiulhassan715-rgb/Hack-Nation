import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

// Dev: /api is proxied to the FastAPI server (make api, port 8000).
// Prod: set VITE_API_BASE to the deployed API; without it the app runs on bundled data.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // maplibre-gl 6 loads its worker relative to its own module URL; pre-bundling moves the
  // module and breaks that, so serve it as-is.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  // maplibre-gl is one ~1 MB chunk (290 kB gzip) on its own; that is expected.
  build: { chunkSizeWarningLimit: 1200 },
  // MapLibre starts its worker as a module worker (see src/map/maplib.ts).
  worker: { format: 'es' },
  server: {
    proxy: {
      '/api': {
        target: process.env.API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
