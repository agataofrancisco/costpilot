import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// O painel fala com a API em /admin/* e, em desenvolvimento, o Vite encaminha para o backend local.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/admin': process.env.COSTPILOT_API_URL || 'http://127.0.0.1:8000',
    },
  },
})
