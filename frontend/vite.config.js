import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// SARVAM_API_KEY (no VITE_ prefix) stays on this machine: the dev server adds it to Sarvam voice-agent requests.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxy = {
    '/api/sarvam': {
      target: 'https://apps.sarvam.ai',
      changeOrigin: true,
      rewrite: (p) => p.replace(/^\/api\/sarvam/, '/api/app-runtime'),
      headers: env.SARVAM_API_KEY ? { 'X-API-Key': env.SARVAM_API_KEY } : {},
    },
  }
  return { plugins: [react()], server: { port: 3000, fs: { allow: ['..'] }, proxy }, preview: { proxy } }
})
