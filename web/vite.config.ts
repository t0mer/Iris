/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Fonts must be real files: the Content-Security-Policy blocks data: fonts.
  build: { outDir: '../app/static', emptyOutDir: true, assetsInlineLimit: 0 },
  server: { proxy: { '/api': 'http://localhost:8080' } },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], globals: true },
})
