import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { DatabaseSync } from 'node:sqlite'
import path from 'node:path'

function productsFallbackPlugin() {
  return {
    name: 'products-fallback-plugin',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ? req.url.split('?')[0] : ''
        // Intercept only GET /api/products or /api/products/
        if (req.method === 'GET' && (url === '/api/products' || url === '/api/products/')) {
          try {
            const dbPath = path.resolve(import.meta.dirname, '../../backend/inventory.db')
            const db = new DatabaseSync(dbPath)
            const rows = db.prepare('SELECT * FROM products WHERE is_active = 1').all()
            const products = rows.map((p) => ({
              ...p,
              is_active: Boolean(p.is_active)
            }))
            res.setHeader('Content-Type', 'application/json')
            res.statusCode = 200
            res.end(JSON.stringify({ data: products, message: 'All products fetched successfully' }))
            return
          } catch (err) {
            console.error('SQLite products fallback error:', err)
          }
        }
        next()
      })
    }
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), productsFallbackPlugin()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/dashboard': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass(req) {
          const url = req.url ? req.url.split('?')[0] : ''
          if (
            (req.headers.accept && req.headers.accept.includes('text/html')) ||
            url === '/dashboard' ||
            url === '/dashboard/'
          ) {
            return '/index.html'
          }
        }
      }
    }
  }
})
