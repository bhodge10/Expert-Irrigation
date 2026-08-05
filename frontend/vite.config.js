import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, Vite serves the app on :5173 and forwards /api to the FastAPI server
// on :8000. Same origin as far as the browser is concerned, so the session
// cookie just works and there's no CORS to configure.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
