import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  build: { outDir: "../app/static/admin", emptyOutDir: true },
  server: { port: 9901, proxy: { "/api": "http://localhost:9900", "/v1": "http://localhost:9900" } },
});
