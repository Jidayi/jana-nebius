// VSL-43, VSL-44 (D103, D106): an online sketch in the conversation. An unchecked sketch carries "Rough sketch, not
// checked" in the hand font beside the engine's spoken notice; a sketch whose checks all passed shows the check chip
// and neither; "Remove sketch" takes it off.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ReactNode } from "react";
import { removeSketch, type SessionController } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { StoreProvider } from "../src/store.js";
import { PartView, TurnView } from "../src/transcript/Turn.js";
import { Fixture } from "./harness.js";

afterEach(() => cleanup());

const SPOKEN = "This is a rough sketch, and I haven't checked it.";

function sketch(status: "checked" | "not_checked", n: string) {
  const checks = status === "checked" ? [{ element: 0, claim: "length", result: "pass", check_id: "chk_len" }] : [];
  return { sketch_id: `skt_${n.repeat(26)}`, sketch_version: 1, frame: { visual_id: null, x_min: 0, x_max: 10, y_min: 0, y_max: 10 },
    elements: [{ kind: "line", from: [0, 0], to: [3, 4] }], dropped: [], checks, status, alt: "Rough sketch: 1 line" };
}

function sketched(f: Fixture, status: "checked" | "not_checked", n: string): string {
  const part = `prt_${n.repeat(26)}`;
  f.emit({ type: "part.start", part_id: part, kind: "visual", index: 1 });
  f.emit({ type: "visual.sketch", part_id: part, sketch: sketch(status, n) });
  f.emit({ type: "part.end", part_id: part, status: "complete", duration_ms: 5 });
  return part;
}

function show(f: Fixture, session: unknown, node: ReactNode) {
  const registry = defaultRegistry();
  registry.register("visual:sketch", { schema: "visuals/sketch#/$defs/resolved", renderClass: "card",
    Component: ({ data }) => <svg data-drawn={(data as { sketch_id: string }).sketch_id} />, Fallback: () => null });
  return render(<LocaleProvider locale="en"><RegistryProvider registry={registry}>
    <StoreProvider holder={f.holder} session={session as SessionController}>{node}</StoreProvider></RegistryProvider></LocaleProvider>);
}

describe("VSL-44", () => {
  test("vsl44_rough_sketch_label_and_spoken_notice", () => {
    const f = new Fixture();
    f.startTurn();
    const rough = sketched(f, "not_checked", "1");
    const said = f.text(SPOKEN);
    const checked = sketched(f, "checked", "2");
    f.end();
    show(f, null, <><PartView partId={rough} /><PartView partId={said} readAloud={false} /><PartView partId={checked} /></>);
    const unchecked = document.querySelector(`[data-part-id="${rough}"]`) as HTMLElement;
    // Drawn by the vetted sketch renderer, labelled in the hand font, with the engine's spoken notice beside it.
    expect(unchecked.querySelector(`[data-drawn="skt_${"1".repeat(26)}"]`)).not.toBeNull();
    const label = unchecked.querySelector("[data-sketch-label]") as HTMLElement;
    expect(label.textContent).toBe("Rough sketch, not checked");
    expect(label.className).toContain("font-hand");
    expect(document.querySelector(`[data-part-id="${said}"]`)?.textContent).toContain(SPOKEN);
    // A sketch whose checks all passed shows the check chip and neither the label nor a notice of its own.
    const passed = document.querySelector(`[data-part-id="${checked}"]`) as HTMLElement;
    expect(passed.querySelector("[data-sketch-label]")).toBeNull();
    expect(passed.querySelector("[data-check-id]")?.getAttribute("data-check-id")).toBe("chk_len");
  });

  test("test_vsl43_remove_sketch_in_the_conversation", async () => {
    const f = new Fixture();
    f.startTurn();
    const part = sketched(f, "not_checked", "3");
    f.end();
    const removed: string[] = [];
    const session = { removeSketch: vi.fn(async (id: string) => { removed.push(id); act(() => f.holder.update((s) => removeSketch(s, id))); }) };
    show(f, session, <PartView partId={part} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Remove sketch" })); });
    expect(removed).toEqual([`skt_${"3".repeat(26)}`]);
    expect(document.querySelector("[data-sketch-part]")).toBeNull();
  });
});


test("completed sketches stay visible outside the folded check summary", () => {
  const f = new Fixture();
  const turn = f.startTurn();
  sketched(f, "not_checked", "4");
  f.end();
  show(f, null, <TurnView turnId={turn} />);
  expect(document.querySelector("[data-sketch-part]")).not.toBeNull();
  expect(screen.queryByRole("button", { name: /check done/ })).toBeNull();
});
