import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to Flask on :5000. This keeps the browser
// talking to a single origin, so the backend needs no CORS configuration
// (and no flask-cors dependency) — see docs/Decisions.md.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:5000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    css: false,
  },
});
