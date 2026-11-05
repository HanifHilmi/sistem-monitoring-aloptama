import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': process.env.SIMOLA_API_URL ?? 'http://127.0.0.1:8000' },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id: string) => (/node_modules\/(echarts|zrender)\//.test(id) ? 'echarts' : undefined),
      },
    },
  },
  // Unit tests only; the browser tests in e2e/ run with Playwright (npm run e2e).
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
})
