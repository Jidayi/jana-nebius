import { readFileSync } from "node:fs";
import path from "node:path";
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { GalleryView, STATES } from "../gallery/index.js";
import { renderTex } from "../src/maths/katex.js";

afterEach(cleanup);
test.each(["light", "dark"])("uia19_changed_macro: %s", (theme) => {
  const state = STATES.find((s) => s.id === "board-step.canonical.changed-term")!;
  const { container } = render(<GalleryView state={{ ...state, context: { ...state.context, theme } }} />);
  const visual = container.querySelector(".katex-html .changed")!;
  expect(visual.textContent).toBe("2(−10)s");
  expect(visual.closest("[aria-hidden=true]")).not.toBeNull();
  const marker = container.querySelector("math mtext")!;
  expect(marker.textContent?.trim()).toBe("changed:");
  expect(marker.parentElement?.textContent).toBe("changed: 2(−10)s");
  expect(marker.closest("[aria-hidden=true]")).toBeNull();
  const css = readFileSync(path.resolve(import.meta.dirname, "../src/styles/ui.css"), "utf8");
  const rule = /\.katex-html \.changed\s*\{([^}]+)\}/.exec(css)![1]!;
  expect(rule).toContain("background-color: var(--color-highlight-soft)");
  expect(rule).toContain("text-decoration-line: underline");
});

test("changed terms preserve nesting, multiple markers, escaping and memoized output", () => {
  for (const [tex, count] of [["x + \\changed{\\frac{2}{3}} + \\changed{y}", 2], ["\\changed{a+\\changed{b}}", 2], ["x=2", 0]] as const) {
    const out = renderTex(tex, false); expect("html" in out).toBe(true);
    if (!("html" in out)) throw new Error(out.error);
    const root = document.createElement("div"); root.innerHTML = out.html;
    expect(root.querySelectorAll(".katex-html .changed")).toHaveLength(count);
    expect([...root.querySelectorAll("math mtext")].filter((m) => m.textContent?.trim() === "changed:")).toHaveLength(count);
    expect(renderTex(tex, false)).toBe(out);
    expect(root.querySelector("script")).toBeNull();
  }
});
