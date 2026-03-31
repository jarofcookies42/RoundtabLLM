import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/chat': 'http://localhost:8000',
      '/conversations': 'http://localhost:8000',
      '/context': 'http://localhost:8000',
      '/import': 'http://localhost:8000',
    },
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
})
