// The contract fixture corpus validates in TypeScript exactly as labelled (M1.a cross-language parity).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { errors } from "../src/generated/index.js";

const corpus = path.resolve(import.meta.dirname, "../../../evals/contracts");
const index: { file: string; contract: string; expect: "valid" | "invalid" }[] = JSON.parse(
  fs.readFileSync(path.join(corpus, "index.json"), "utf8"),
);

describe("contract fixture corpus", () => {
  test.each(index)("$file is $expect", ({ file, contract, expect: expected }) => {
    const data: unknown = JSON.parse(fs.readFileSync(path.join(corpus, file), "utf8"));
    const problems = errors(contract, data);
    if (expected === "valid") expect(problems).toEqual([]);
    else expect(problems.length).toBeGreaterThan(0);
  });
});
