/** @file vite.config.js @description Frontend build and same-origin development API proxy. */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(['/api', '/auth', '/status', '/history', '/check', '/healthz'].map(path => [path, 'http://127.0.0.1:18080'])),
  },
});
