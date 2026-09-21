import { defineConfig } from 'vite';

const target = process.env.WS_WEB_URL || 'http://127.0.0.1:8765';
const backend = new URL(target);
if (backend.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(backend.hostname)) {
  throw new Error('WS_WEB_URL must point to a local ws web server.');
}

export default defineConfig({
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target, changeOrigin: true,
        configure: proxy => proxy.on('proxyReq', request => request.setHeader('Origin', backend.origin)),
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: id => id.includes('node_modules/uidl-runtime/') ? 'uidl-runtime'
          : id.includes('node_modules/') ? 'vendor' : undefined,
      },
    },
  },
});
