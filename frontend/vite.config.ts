import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Local operator plane. Run it with:
      //   SST_DB_PATH=... SST_MCP_TOKEN=... \
      //   conda run -n agentic-graphrag python -m mcp_server.http --operator
      // Proxying keeps the browser same-origin, so no CORS layer is needed on
      // a plane that should only ever listen on loopback.
      "/operator": {
        target: process.env.VITE_OPERATOR_TARGET ?? "http://127.0.0.1:8137",
        changeOrigin: true,
      },
      // `/graph` is the read-only map plane the ambient canvas reads.
      "/graph": {
        target: process.env.VITE_OPERATOR_TARGET ?? "http://127.0.0.1:8137",
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    // layout-wasm ships its own workers / wasm assets — don't prebundle it.
    exclude: ["@antv/layout-wasm"],
  },
  worker: {
    // layout-wasm workers import split WASM/JS chunks; IIFE cannot code-split.
    format: "es",
  },
});
