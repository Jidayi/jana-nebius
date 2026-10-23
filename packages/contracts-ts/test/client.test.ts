import fs from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";
import { errors, validators } from "../src/client.js";
import { errors as fullErrors, validators as fullValidators } from "../src/index.js";
const corpus = path.resolve(import.meta.dirname, "../../../evals/contracts");
const index: { file: string; contract: string }[] = JSON.parse(fs.readFileSync(path.join(corpus, "index.json"), "utf8"));

test("learner validators preserve corpus parity and exclude server/authoring entry points", () => {
  expect(Object.keys(validators).length).toBeLessThan(Object.keys(fullValidators).length / 2);
  expect(validators["api/events"]).toBeTypeOf("function");
  expect(() => errors("content/content-pack", {})).toThrow("unknown contract");
  let checked = 0;
  for (const { file, contract } of index) {
    if (validators[contract] === undefined) continue;
    const data: unknown = JSON.parse(fs.readFileSync(path.join(corpus, file), "utf8"));
    expect(errors(contract, data), file).toEqual(fullErrors(contract, data)); checked++;
  }
  expect(checked).toBeGreaterThan(80);
});
