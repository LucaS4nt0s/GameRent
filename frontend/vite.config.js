import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Alvos do proxy de desenvolvimento; dá para apontar para outra stack sem mexer no arquivo:
// CATALOG_TARGET=http://localhost:8011 RENTAL_TARGET=http://localhost:8012 npm run dev
const CATALOG_TARGET = process.env.CATALOG_TARGET || 'http://localhost:8001'
const RENTAL_TARGET = process.env.RENTAL_TARGET || 'http://localhost:8002'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api/catalog': {
        target: CATALOG_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/catalog/, ''),
      },
      '/api/rental': {
        target: RENTAL_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/rental/, ''),
      },
    },
  },
})
