// UIA-27: the specification's conceptual components mapped to their actual composed gallery views.
import { readFileSync } from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { RENDERERS } from "@jana/renderers";
import { defaultRegistry } from "@jana/ui";
import { DECLARED, GalleryView, STATES } from "@jana/ui/gallery";
import inventory from "../../../packages/ui/gallery/inventory.json";
import { registerVisuals } from "../src/visuals.js";

afterEach(cleanup);
const registry = () => registerVisuals(defaultRegistry(), RENDERERS);
type Entry = { fixture: string; selector: string; click?: string; part?: boolean };

test.each(Object.entries(inventory) as [string, Entry][])("uia27_inventory_gallery_coverage: %s", async (name, entry) => {
    const state = STATES.find((s) => s.id === entry.fixture);
    expect(state, name).toBeDefined(); expect(state!.state, name).toBe("canonical");
    const { container } = render(<GalleryView state={state!} registry={registry()} />);
    if (entry.click) fireEvent.click(container.querySelector(entry.click)!);
    if (entry.part) {
      const select = container.querySelector<HTMLSelectElement>("select[data-part-equivalents]")!;
      expect(select.options.length).toBeGreaterThan(1); fireEvent.change(select, { target: { value: select.options[1]!.value } });
    }
    await waitFor(() => expect(container.querySelector(entry.selector), `${name}: ${entry.selector}`).not.toBeNull());
    expect(container.querySelector("[data-wildcard]")).toBeNull();
    cleanup();
});

test("the inventory is exactly the specification table and all declared states exist", () => {
  const spec = readFileSync(path.resolve(import.meta.dirname, "../../../docs/specification/ui-architecture.md"), "utf8").split("### UIA-27")[1]!.split("Acceptance:")[0]!;
  const names = [...spec.matchAll(/`([^`]+)`/g)].map((m) => m[1]);
  expect(Object.keys(inventory).sort()).toEqual(names.sort());

  // Every declared state is data, and every shipped renderer kind has a real canonical visual.
  for (const [component, states] of Object.entries(DECLARED)) for (const state of states) expect(STATES.some((s) => s.component === component && s.state === state), `${component}/${state}`).toBe(true);
  for (const renderer of RENDERERS) {
    const state = STATES.find((s) => s.component === "VisualViewer" && s.state === "canonical" && s.payload.type === renderer.kind);
    expect(state, renderer.kind).toBeDefined();
    const { container } = render(<GalleryView state={state!} registry={registry()} />);
    expect(container.querySelector(`[data-visual-viewer="${renderer.kind}"]`)).not.toBeNull();
    expect(container.querySelector('[data-visual-viewer="fallback"]')).toBeNull(); cleanup();
  }
});
