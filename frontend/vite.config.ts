import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Inject a build timestamp so every production build produces a unique bundle
  // filename — prevents browsers from serving stale cached bundles when the hash
  // happens to collide with a prior build.
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  server: {
    port: 5173,
    // Proxy /api/* to the backend without rewriting the path.
    // api.ts already uses the absolute base URL so this proxy is only active
    // in dev mode (npm run dev) as a fallback.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
