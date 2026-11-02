import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `vite preview` behind a temporary tunnel (WALKTHROUGH §13): the app and the API share one
// origin, so a build with VITE_API_BASE_URL=. needs no CORS change and one public URL.
export default defineConfig({
  plugins: [react()],
  preview: {
    allowedHosts: ['.trycloudflare.com'],
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
