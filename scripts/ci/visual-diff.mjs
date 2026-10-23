import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";

export function visualDiff(before, after) {
  const a = PNG.sync.read(before), b = PNG.sync.read(after);
  if (a.width !== b.width || a.height !== b.height) return { failure: "Screenshot dimensions changed.", ratio: 1, image: after };
  const diff = new PNG({ width: a.width, height: a.height });
  const pixels = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold: 0.1 });
  const ratio = pixels / (a.width * a.height);
  return { failure: ratio > 0.001 ? "More than 0.1% of screenshot pixels changed; review required." : null, ratio, image: PNG.sync.write(diff) };
}
