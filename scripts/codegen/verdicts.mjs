// Validate every fixture of the contract corpus with the generated TypeScript validators and print
// {file: "valid" | "invalid"} as JSON, for the cross-language parity check (scripts/tests).
import fs from "node:fs";
import path from "node:path";
import { isValid } from "../../packages/contracts-ts/src/generated/index.ts";

const corpus = path.resolve(import.meta.dirname, "../../evals/contracts");
const index = JSON.parse(fs.readFileSync(path.join(corpus, "index.json"), "utf8"));
const verdicts = {};
for (const entry of index) {
  const data = JSON.parse(fs.readFileSync(path.join(corpus, entry.file), "utf8"));
  verdicts[entry.file] = isValid(entry.contract, data) ? "valid" : "invalid";
}
process.stdout.write(JSON.stringify(verdicts));
