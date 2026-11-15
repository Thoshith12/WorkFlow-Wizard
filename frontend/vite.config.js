import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  // Load VITE_* vars from the correct .env file for the current mode.
  // These drive which host each /api/* prefix is proxied to during dev.
  const env = loadEnv(mode, process.cwd(), '');

  const backendTarget = env.VITE_BACKEND_URL || 'http://localhost:8000';
  const ragTarget    = env.VITE_RAG_URL     || 'http://localhost:8001';
  const toolsTarget  = env.VITE_TOOLS_URL   || 'http://localhost:8002';

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        // More-specific prefixes must come BEFORE the catch-all /api rule.
        '/api/data-sources': {
          target: ragTarget,
          changeOrigin: true,
          secure: false,
        },
        '/api/tools': {
          target: toolsTarget,
          changeOrigin: true,
          secure: false,
        },
        // Catch-all: everything else under /api → main backend
        '/api': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
        },
      },
    },
  };
});
