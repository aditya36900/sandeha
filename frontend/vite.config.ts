import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const API = process.env.SANDEHA_API || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': API,
      '/media': API,
      '/verify': API,
      '/ws': { target: API.replace(/^http/, 'ws'), ws: true }
    }
  }
});
