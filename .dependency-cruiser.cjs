// ARC-18 and ARC-19 dependency rules for the TypeScript packages (Python rules: .importlinter).
const HTTP_CLIENTS = ["axios", "ky", "got", "node-fetch", "undici", "superagent", "cross-fetch", "isomorphic-fetch"];
const MODEL_SDKS = [
  "openai", "@anthropic-ai", "ollama", "@google/generative-ai", "@google/genai", "@mistralai", "groq-sdk",
  "cohere-ai", "@huggingface/inference", "langchain", "@langchain", "llamaindex", "ai", "@ai-sdk", "node-llama-cpp",
];
// A package matches whether it resolved (inside node_modules) or not (bare specifier).
const packages = (names) => names.flatMap((n) => [`node_modules/${n}/`, `^${n}$`, `^${n}/`]);
const CLIENTS = "^(packages/(ui|client-core|renderers|contracts-ts|i18n)|apps/(desktop/src|web|android|studio))/";

/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "arc18-ui-imports",
      comment: "packages/ui may import only client-core, contracts-ts and i18n",
      severity: "error",
      from: { path: "^packages/ui/" },
      to: { path: "^(apps/|packages/(?!(ui|client-core|contracts-ts|i18n)/))" },
    },
    {
      name: "arc18-renderers-imports",
      comment: "packages/renderers may import only client-core, contracts-ts and i18n",
      severity: "error",
      from: { path: "^packages/renderers/" },
      to: { path: "^(apps/|packages/(?!(renderers|client-core|contracts-ts|i18n)/))" },
    },
    {
      name: "arc18-ui-no-http-client",
      comment: "packages/ui and renderers never import an HTTP client",
      severity: "error",
      from: { path: "^packages/(ui|renderers)/" },
      to: {
        path: [...packages(HTTP_CLIENTS), "^(node:)?(http|https|http2|net|tls|dgram)$"],
      },
    },
    {
      name: "arc19-no-model-sdk",
      comment: "no client package contains a model SDK (ARC-19)",
      severity: "error",
      from: { path: CLIENTS },
      to: { path: packages(MODEL_SDKS) },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    exclude: { path: "(^|/)(dist|node_modules|coverage)/|^apps/prototype-s0/|^docs/" },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.base.json" },
    enhancedResolveOptions: { exportsFields: ["exports"], conditionNames: ["import", "require", "node", "default"] },
  },
};
