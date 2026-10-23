import { defineConfig } from "vitest/config";

export default defineConfig({
  // Browser journeys each launch Chromium and build the gallery. Bound concurrent suites so
  // they do not exhaust memory or starve short interaction assertions on supported laptops.
  test: { include: ["test/**/*.test.{ts,tsx}"], environment: "happy-dom", setupFiles: ["./test/browser-build-setup.ts"], testTimeout: 120_000, maxWorkers: 2 },
  esbuild: { jsx: "automatic" },
});
