import fs from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";
import { canPractise, type VisualSpec } from "../src/visuals/VisualViewer.js";

const fixture = (name: string): VisualSpec => JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, `../../renderers/fixtures/visuals/${name}.json`), "utf8")).spec;

test("practice uses actual checked diagram parts rather than part-id punctuation", () => {
  expect(canPractise(fixture("number-line"), "sol.from")).toBe(true);
  expect(canPractise(fixture("number-line"), "sol.to")).toBe(false); // infinite endpoint
  expect(canPractise(fixture("function-graph"), "f.root1")).toBe(true);
  expect(canPractise(fixture("function-graph"), "f.unknown")).toBe(false);
  expect(canPractise(fixture("free-body"), "W")).toBe(true);
  expect(canPractise(fixture("free-body"), "object")).toBe(false);
  expect(canPractise(fixture("cycle-diagram"), "plants")).toBe(false);
  expect(canPractise({ ...fixture("number-line"), numbers_from: null }, "sol.from")).toBe(false);
});
