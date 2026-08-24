import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 開発サーバーは 5173（バックエンドの CORS_ORIGINS の既定値と一致）
// /api へのリクエストは FastAPI（http://localhost:8000）へプロキシする
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
