import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["**/dist/**", "**/node_modules/**", ".venv/**", "target/**", "apps/*/src-tauri/resources/**", "apps/prototype-s0/**", "docs/**", ".claude/**", "packages/contracts-ts/src/generated/**"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  { files: ["**/*.cjs"], languageOptions: { sourceType: "commonjs", globals: globals.node } },
  { files: ["*.js", "scripts/**/*.js", "scripts/**/*.mjs", "services/**/*.mjs"], languageOptions: { globals: globals.node } },
  // The ingest's support upload page runs in a browser (OPS-24).
  { files: ["services/ingest/ingest/page/*.js"], languageOptions: { sourceType: "script", globals: globals.browser } },
  {
    rules: {
      // `const { dropped: _dropped, ...rest } = record` is how a field is left out of a copy.
      "@typescript-eslint/no-unused-vars": ["error", { ignoreRestSiblings: true, varsIgnorePattern: "^_", argsIgnorePattern: "^_" }],
    },
  },
  // Tests index fixtures they just built; a failed assertion is the test failing, not a crash to guard against.
  { files: ["**/test/**/*.ts", "**/*.test.ts", "**/*.test.tsx"], rules: { "@typescript-eslint/no-non-null-assertion": "off" } },
);
