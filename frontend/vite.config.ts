import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/state': 'http://localhost:5000',
      '/start': 'http://localhost:5000',
      '/stop': 'http://localhost:5000',
      '/sessions': 'http://localhost:5000',
      '/session': 'http://localhost:5000',
      '/socket.io': {
        target: 'http://localhost:5000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
