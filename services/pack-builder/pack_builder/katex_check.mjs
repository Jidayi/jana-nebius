// The maths-rendering check of the pack build (CUR-25): every LaTeX string is rendered with the KaTeX the client
// bundles, with the client's options (packages/ui/src/maths/katex.ts, UIA-15). Reads {from, maxExpand, maxSize, tex}
// as JSON on stdin and writes {errors: {index: message}} for the strings KaTeX refuses.
import { createRequire } from "node:module";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const katex = createRequire(request.from)("katex");
const ALLOWED_CLASS = /^(changed|term-[a-z0-9-]+)$/;
const trust = (context) =>
  context.command === "\\htmlClass" &&
  typeof context.class === "string" &&
  context.class.split(/\s+/).every((c) => ALLOWED_CLASS.test(c));

const errors = {};
request.tex.forEach((tex, index) => {
  try {
    katex.renderToString(tex, {
      displayMode: true,
      throwOnError: true,
      output: "htmlAndMathml",
      trust,
      strict: "ignore",
      maxExpand: request.maxExpand,
      maxSize: request.maxSize,
      macros: { "\\changed": "\\htmlClass{changed}{#1}" },
    });
  } catch (error) {
    errors[index] = error instanceof Error ? error.message : String(error);
  }
});
process.stdout.write(JSON.stringify({ errors }));
