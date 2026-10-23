import { test } from "node:test";
import assert from "node:assert/strict";
import { PNG } from "pngjs";
import { visualDiff } from "./visual-diff.mjs";
function image(size, changed = 0) {
  const png = new PNG({ width: size, height: size }); png.data.fill(255);
  for (let n = 0; n < changed; n++) { png.data[n * 4] = 0; png.data[n * 4 + 1] = 0; png.data[n * 4 + 2] = 0; }
  return PNG.sync.write(png);
}
test("unchanged screenshots pass, a visible token change produces a reviewable diff", () => {
  assert.equal(visualDiff(image(100), image(100)).failure, null);
  assert.ok(visualDiff(image(100), image(100, 100)).failure);
  assert.equal(visualDiff(image(100), image(100, 100)).ratio, .01);
});
test("a resized screenshot cannot pass as a zero pixel difference", () => {
  assert.match(visualDiff(image(100), image(101)).failure, /dimensions/);
});
