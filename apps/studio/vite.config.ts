import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import { studioBridge } from "./dev/bridge.js";
export default defineConfig({
  plugins: [react(), tailwindcss(), studioBridge()], server: { host: "127.0.0.1", port: 5191, strictPort: true },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: "contracts", test: /contracts-ts[\\/]src[\\/]generated[\\/]client-validators\.js/ },
            { name: "editor", test: /node_modules[\\/](?:\.pnpm[\\/][^/]+[\\/]node_modules[\\/])?(?:@tiptap|prosemirror-)/ },
            { name: "maths", test: /node_modules[\\/](?:\.pnpm[\\/][^/]+[\\/]node_modules[\\/])?katex[\\/]/ },
          ],
        },
      },
    },
  },
  clearScreen: false,
});
