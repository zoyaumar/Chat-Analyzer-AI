import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Dev only: the browser talks to Vite, which forwards API and WebSocket
  // traffic to FastAPI. Override with VITE_DEV_API_TARGET in chat_frontend/.env
  // (docs/DESIGN_DECISIONS.md Q34).
  const { VITE_DEV_API_TARGET } = loadEnv(mode, '.', '')
  const apiTarget = VITE_DEV_API_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/users': apiTarget,
        '/messages': apiTarget,
        '/analytics': apiTarget,
        '/docs': apiTarget,
        '/redoc': apiTarget,
        '/openapi.json': apiTarget,
        '/health': apiTarget,
        '/ws': { target: apiTarget, ws: true },
      },
    },
  }
})
