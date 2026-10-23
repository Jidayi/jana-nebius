import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { SessionController, StoreHolder, typedCapture } from "@jana/client-core";
import { PhotoCapture } from "../src/composer/PhotoCapture.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
const SID = `ses_${"0".repeat(26)}`, QUAD = [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }];
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function mount() {
  const crop: { corners: { x: number; y: number }[]; preview_only?: boolean; rotation: number }[] = [], reads: unknown[] = [];
  const capture = { ...typedCapture("", { sessionId: SID, purpose: "question", confirmed: false }), source: "photo_file" };
  const holder = new StoreHolder(), session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, SID, { fetch: async (url, init) => {
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    if (String(url).endsWith("/crop")) crop.push(JSON.parse(String(init?.body)));
    if (String(url).endsWith("/read")) reads.push(JSON.parse(String(init?.body)));
    return Response.json({ ...capture, outline: QUAD });
  } });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-crop"); vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const file = new Blob([readFileSync(path.resolve(import.meta.dirname, "../gallery/photo-source-fixture.jpg"))], { type: "image/jpeg" });
  const view = render(<LocaleProvider locale="en"><StoreProvider holder={holder} session={session}><PhotoCapture file={file} sessionId={SID} purpose="question" onConfirmed={vi.fn()} onTyped={vi.fn()} onClose={vi.fn()} /></StoreProvider></LocaleProvider>);
  return { ...view, crop, reads, session };
}
test("inp17_keyboard_corners: four ordered keyboard handles reach the actual crop command", async () => {
  const view = mount();
  try {
    await waitFor(() => expect(view.crop).toHaveLength(1));
    for (let index = 0; index < 4; index++) {
      const button = screen.getByRole("button", { name: `Crop corner ${index + 1}`, exact: true }), point = QUAD[index]!;
      fireEvent.keyDown(button, { key: point.x === 0 ? "ArrowRight" : "ArrowLeft" });
      fireEvent.keyDown(button, { key: point.y === 0 ? "ArrowDown" : "ArrowUp", shiftKey: true });
      expect(button.getAttribute("aria-description")).toBe(`${point.x === 0 ? 1 : 99}% from the left; ${point.y === 0 ? 5 : 95}% from the top. Arrow keys move 1%; Shift moves 5%.`);
    }
    fireEvent.click(screen.getByRole("button", { name: "Use this area" }));
    await waitFor(() => expect(view.reads).toHaveLength(1));
    expect(view.crop).toHaveLength(2); expect(view.crop[1]?.preview_only).toBeUndefined(); expect(view.crop[1]?.rotation).toBe(0);
    for (const [index, point] of QUAD.entries()) {
      expect(view.crop[1]?.corners[index]?.x).toBeCloseTo(point.x === 0 ? .01 : .99);
      expect(view.crop[1]?.corners[index]?.y).toBeCloseTo(point.y === 0 ? .05 : .95);
    }
    expect(view.reads[0]).toEqual({ override_quality: false, send_to_cloud: false });
  } finally { view.unmount(); view.session.close(); }
});
test("crop handles clamp outward movement and ignore unrelated keys", async () => {
  const view = mount();
  try {
    await waitFor(() => expect(view.crop).toHaveLength(1));
    for (let index = 0; index < 4; index++) {
      const button = screen.getByRole("button", { name: `Crop corner ${index + 1}`, exact: true }), point = QUAD[index]!;
      const before = button.getAttribute("aria-description");
      fireEvent.keyDown(button, { key: point.x === 0 ? "ArrowLeft" : "ArrowRight", shiftKey: true });
      fireEvent.keyDown(button, { key: point.y === 0 ? "ArrowUp" : "ArrowDown" });
      fireEvent.keyDown(button, { key: "a" }); expect(button.getAttribute("aria-description")).toBe(before);
    }
  } finally { view.unmount(); view.session.close(); }
});
