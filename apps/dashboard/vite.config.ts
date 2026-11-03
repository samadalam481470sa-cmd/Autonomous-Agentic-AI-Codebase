import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dashboard is served by the FastAPI app under /dashboard and talks to the
// same origin, so no production proxy or CORS configuration is required.
export default defineConfig({
  base: '/dashboard/',
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
    emptyOutDir: true,
  },
  server: {
    host: '127.0.0.1',
    port: 5175,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
});
