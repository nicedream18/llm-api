import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig(({ mode }) => mode === "landing" ? {
  plugins: [react()],
  root: fileURLToPath(new URL("./landing", import.meta.url)),
  base: "/landing/",
  build: { outDir: fileURLToPath(new URL("../app/static/landing", import.meta.url)), emptyOutDir: true },
  server: { port: 9902, proxy: { "/admin": "http://localhost:9900", "/api": "http://localhost:9900" } },
} : {
  plugins: [react()],
  base: "/admin/",
  build: { outDir: "../app/static/admin", emptyOutDir: true },
  server: { port: 9901, proxy: { "/api": "http://localhost:9900", "/v1": "http://localhost:9900" } },
});
