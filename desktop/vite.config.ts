import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/desktop/",
  resolve: { alias: {
    "@tauri-apps/plugin-opener": fileURLToPath(new URL("./src/lib/native.ts", import.meta.url)),
    "@tauri-apps/plugin-dialog": fileURLToPath(new URL("./src/lib/native.ts", import.meta.url)),
    "@tauri-apps/api/event": fileURLToPath(new URL("./src/lib/runtime.ts", import.meta.url)),
  } },
  build: { outDir: "../app/static/desktop", emptyOutDir: true },
  server: { host: "localhost", port: 9902, strictPort: true, proxy: { "/api": "http://localhost:9910", "/v1": "http://localhost:9910", "/health": "http://localhost:9910" } },
});
