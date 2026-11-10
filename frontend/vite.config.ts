import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes inside the Python package so the backend can serve it.
// In development, run `screener serve --port 8765 --no-browser` next to `npm run dev`.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/screener/web", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
