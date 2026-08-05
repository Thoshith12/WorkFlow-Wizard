import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api/data-sources': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false,
      },
      '/api/tools': {
        target: 'http://localhost:8002',
        changeOrigin: true,
        secure: false,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
