import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: process.env.BACKEND_URL ?? 'http://localhost:8000' },
      '/admin': { target: process.env.BACKEND_URL ?? 'http://localhost:8000' },
      '/static': { target: process.env.BACKEND_URL ?? 'http://localhost:8000' },
    },
  },
  // Bound jsdom workers so Docker/CI does not start one heavy environment per host CPU.
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], maxWorkers: 2 },
})
