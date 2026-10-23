import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import path from "node:path";
import { readFileSync } from "node:fs";
import { afterEach, expect, test, vi } from "vitest";
import { SessionController, typedCapture } from "@jana/client-core";
import { Composer } from "../src/composer/Composer.js";
import { Board } from "../src/board/Board.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
import { Fixture, SESSION } from "./harness.js";
const jpeg = new Uint8Array(readFileSync(path.resolve(import.meta.dirname, "../gallery/photo-source-fixture.jpg")));
const mediaDescriptor = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
afterEach(() => { cleanup(); vi.restoreAllMocks(); if (mediaDescriptor) Object.defineProperty(navigator, "mediaDevices", mediaDescriptor); else Reflect.deleteProperty(navigator, "mediaDevices"); });
function mount(board = false) {
  const fixture = new Fixture(); fixture.startTurn(); fixture.end();
  const uploaded: { meta: Record<string, unknown>; bytes: Uint8Array }[] = [], crops: Record<string, unknown>[] = [];
  let capture = typedCapture("", { sessionId: SESSION, purpose: "question", confirmed: false });
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, fixture.holder, SESSION, {
    fetch: async (url, init) => {
      const path = new URL(String(url)).pathname;
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      if (path === "/v1/captures" && init?.method === "POST") {
        const form = init.body as FormData, meta = JSON.parse(String(form.get("meta"))), file = form.get("file") as File;
        uploaded.push({ meta, bytes: new Uint8Array(await file.arrayBuffer()) });
        capture = { ...capture, source: meta.source, purpose: meta.purpose };
        return Response.json(capture);
      }
      if (path.endsWith("/crop")) { crops.push(JSON.parse(String(init?.body))); return Response.json({ ...capture, outline: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }] }); }
      if (path.endsWith("/captures")) return Response.json({ captures: [] });
      return Response.json({ document: {}, revision: 0 });
    },
  });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-local-fixture"); vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const view = render(<LocaleProvider locale="en"><StoreProvider holder={fixture.holder} session={session}>{board ? <Board sessionId={SESSION} /> : <Composer sessionId={SESSION} asking />}</StoreProvider></LocaleProvider>);
  return { ...view, fixture, session, uploaded, crops };
}
for (const [format, mime] of [["jpg", "image/jpeg"], ["png", "image/png"], ["webp", "image/webp"]] as const) {
  for (const source of ["file", "paste", "drop", "board_drop"] as const) test(`inp15_sources_equivalent: ${format} ${source}`, async () => {
    const bytes = new Uint8Array(readFileSync(path.resolve(import.meta.dirname, `../gallery/photo-source-fixture.${format}`))), file = new File([bytes], `synthetic.${format}`, { type: mime });
    const view = mount(source === "board_drop");
    try {
      if (source === "file") {
        fireEvent.click(screen.getByRole("button", { name: "Photo of a question", exact: true }));
        fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [file] } });
      } else {
        const target = source === "board_drop" ? view.container.querySelector("section")! : screen.getByRole("textbox", { name: "Message to the tutor" });
        const transfer = { files: [file], types: ["Files"], getData: () => "" };
        if (source === "paste") fireEvent.paste(target, { clipboardData: transfer });
        else { fireEvent.dragOver(target, { dataTransfer: transfer }); expect(screen.getByText("Drop the photo here")).toBeTruthy(); fireEvent.drop(target, { dataTransfer: transfer }); }
      }
      await waitFor(() => expect(view.crops).toHaveLength(1));
      expect(view.uploaded).toHaveLength(1); expect(view.uploaded[0]?.bytes).toEqual(bytes);
      expect(view.uploaded[0]?.meta).toMatchObject({ session_id: SESSION, source: source === "file" ? "photo_file" : source === "paste" ? "photo_paste" : "photo_drop", purpose: source === "board_drop" ? "working" : "question" });
      expect(view.crops[0]).toMatchObject({ preview_only: true, rotation: 0 });
      expect(screen.getByRole("button", { name: "Crop corner 1" })).toBeTruthy();
    } finally { view.unmount(); view.session.close(); }
  });
}
test("inp15_sources_equivalent: synthetic webcam encoder boundary delivers the same JPEG fixture", async () => {
  const stop = vi.fn(), feed = new MediaStream();
  Object.defineProperty(feed, "getTracks", { value: () => [{ stop }] });
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn(async () => feed), enumerateDevices: vi.fn(async () => []) } });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => callback(new Blob([jpeg], { type: "image/jpeg" })));
  const view = mount();
  try {
    fireEvent.click(screen.getByRole("button", { name: "Photo of a question", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Use camera" }));
    const video = await screen.findByLabelText("Live camera preview");
    Object.defineProperties(video, { videoWidth: { value: 900 }, videoHeight: { value: 700 } });
    fireEvent.click(screen.getByRole("button", { name: "Take photo" }));
    await waitFor(() => expect(view.crops).toHaveLength(1));
    expect(view.uploaded[0]?.bytes).toEqual(jpeg); expect(view.uploaded[0]?.meta).toMatchObject({ source: "webcam", purpose: "question" });
    expect(stop).toHaveBeenCalledTimes(1);
  } finally { view.unmount(); view.session.close(); }
});
test("paste/drop respect the same unavailable capture state as the button", async () => {
  const view = mount();
  try {
    act(() => { view.fixture.startTurn(); });
    expect(screen.getByRole("button", { name: "Photo of a question", exact: true }).hasAttribute("disabled")).toBe(true);
    const target = screen.getByRole("textbox", { name: "Message to the tutor" }), transfer = { files: [new File([jpeg], "synthetic.jpg", { type: "image/jpeg" })], types: ["Files"] };
    fireEvent.paste(target, { clipboardData: transfer }); fireEvent.drop(target, { dataTransfer: transfer });
    await act(async () => { await Promise.resolve(); }); expect(view.uploaded).toHaveLength(0); expect(screen.queryByRole("dialog")).toBeNull();
  } finally { view.unmount(); view.session.close(); }
});

test("inp15_sources_equivalent: synthetic HEIC decoder boundary normalizes before upload", async () => {
  const close = vi.fn();
  vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 900, height: 700, close })));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => callback(new Blob([jpeg], { type: "image/jpeg" })));
  const view = mount();
  try {
    fireEvent.click(screen.getByRole("button", { name: "Photo of a question", exact: true }));
    fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File(["synthetic HEIC decoder input"], "fixture.heic", { type: "image/heic" })] } });
    await waitFor(() => expect(view.crops).toHaveLength(1));
    expect(view.uploaded[0]?.bytes).toEqual(jpeg); expect(view.uploaded[0]?.meta).toMatchObject({ source: "photo_file", purpose: "question" });
    expect(close).toHaveBeenCalledTimes(1);
  } finally { view.unmount(); view.session.close(); vi.unstubAllGlobals(); }
});

test("a board photo cannot follow a session switch", async () => {
  const view = mount(true);
  try {
    const transfer = { files: [new File([jpeg], "synthetic.jpg", { type: "image/jpeg" })], types: ["Files"] };
    fireEvent.drop(view.container.querySelector("section")!, { dataTransfer: transfer });
    await waitFor(() => expect(view.crops).toHaveLength(1));
    expect(screen.getByRole("dialog", { name: "Photo of my working" })).toBeTruthy();
    view.rerender(<LocaleProvider locale="en"><StoreProvider holder={view.fixture.holder} session={view.session}><Board sessionId={`ses_${"1".repeat(26)}`} /></StoreProvider></LocaleProvider>);
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByRole("dialog")).toBeNull(); expect(view.uploaded).toHaveLength(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-local-fixture");
  } finally { view.unmount(); view.session.close(); }
});
