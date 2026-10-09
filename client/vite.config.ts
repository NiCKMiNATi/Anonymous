/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Development only: the Vite dev server proxies /api to the loopback Anonymous server so the
// browser sees one origin. The production-style path is `npm run build` and letting the server
// serve client/dist itself. Both bind to loopback only; there is no authentication yet.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8000" } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
