/// <reference types="vitest/config" />
import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// The X-API-Key is attached here, inside the dev/preview server process. It is read without the
// VITE_ prefix, so Vite never inlines it into the browser bundle. Production uses Nginx the same way.
export default defineConfig(({ mode }) => {
  const repoEnv = loadEnv(mode, path.resolve(__dirname, '../..'), '');
  const localEnv = loadEnv(mode, __dirname, '');
  const backend = localEnv.BACKEND_URL || repoEnv.BACKEND_URL || 'http://127.0.0.1:8000';
  // Pipeline A chạy ở service riêng (processing/main.py); khai báo trước '/api/v1' để được ưu tiên.
  const processing = localEnv.PROCESS_URL || repoEnv.PROCESS_URL || 'http://127.0.0.1:8100';
  const apiKey = localEnv.TEST_API_KEY || repoEnv.TEST_API_KEY || '';

  const proxy = {
    '/api/v1/process': {
      target: processing,
      changeOrigin: true,
      rewrite: (p: string) => p.replace(/^\/api/, ''),
      headers: apiKey ? { 'X-API-Key': apiKey } : undefined,
    },
    '/api/v1': {
      target: backend,
      changeOrigin: true,
      rewrite: (p: string) => p.replace(/^\/api/, ''),
      headers: apiKey ? { 'X-API-Key': apiKey } : undefined,
    },
    '/api/thumbs': {
      target: backend,
      changeOrigin: true,
      rewrite: (p: string) => p.replace(/^\/api/, ''),
    },
  };

  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
    // Mermaid is lazy-loaded on /docs only; its own chunks exceed the default warning size.
    build: { target: 'es2022', chunkSizeWarningLimit: 800 },
    test: { environment: 'node', include: ['src/**/*.test.ts'] },
  };
});
