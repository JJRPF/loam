import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Precaches the app shell. API responses and map tiles are deliberately not cached by the service
    // worker (tile providers' terms); recently viewed routes are kept by the app itself (offlineRoutes.ts).
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      manifest: false, // public/manifest.json is the manifest
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,json,mjs}'],
        globIgnores: ['**/*.map', '**/maplibre-gl-worker-dev.mjs'],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/health/],
        cleanupOutdatedCaches: true
      }
    })
  ],
  // VITE_FIREBASE_* come from the repo-root .env (the same file the API reads).
  envDir: '..',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true
      },
      '/health': {
        target: 'http://localhost:8080',
        changeOrigin: true
      }
    }
  }
})
