import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Same origin in dev: /api is proxied to FastAPI, so the httpOnly session cookie just works (as on Vercel).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
