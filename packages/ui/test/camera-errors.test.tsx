import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { SessionController, StoreHolder, typedCapture } from "@jana/client-core";
import { PhotoCapture } from "../src/composer/PhotoCapture.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
const SID = `ses_${"0".repeat(26)}`, descriptor = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
afterEach(() => { cleanup(); vi.restoreAllMocks(); if (descriptor) Object.defineProperty(navigator, "mediaDevices", descriptor); else Reflect.deleteProperty(navigator, "mediaDevices"); });
const cases = [
  ["NotFoundError", "No camera found. You can choose a photo instead."],
  ["NotAllowedError", "The camera is blocked. An adult can allow it in your computer's settings."],
  ["NotReadableError", "Another app is using the camera. You can choose a photo instead."],
  ["SecurityError", "The camera is blocked. An adult can allow it in your computer's settings."],
  ["AbortError", "The camera is unavailable. Check camera permission or choose a photo."],
  ["missing_api", "No camera found. You can choose a photo instead."],
];
test.each(cases)("inp16_camera_error_states: %s has exact copy and a working file fallback", async (name, copy) => {
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: name === "missing_api" ? undefined : { getUserMedia: vi.fn(async () => { throw new DOMException("Synthetic camera refusal", name); }) } });
  const uploads: { source: string; purpose: string; bytes: Uint8Array }[] = [], crops: unknown[] = [], holder = new StoreHolder();
  const capture = typedCapture("", { sessionId: SID, purpose: "question", confirmed: false });
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, SID, {
    fetch: async (url, init) => {
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      if (new URL(String(url)).pathname === "/v1/captures") {
        const body = init?.body as FormData, meta = JSON.parse(String(body.get("meta")));
        uploads.push({ ...meta, bytes: new Uint8Array(await (body.get("file") as File).arrayBuffer()) });
      } else if (String(url).endsWith("/crop")) crops.push(JSON.parse(String(init?.body)));
      return Response.json(capture);
    },
  });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-fallback"); vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const choose = vi.spyOn(HTMLInputElement.prototype, "click");
  const view = render(<LocaleProvider locale="en"><StoreProvider holder={holder} session={session}><PhotoCapture sessionId={SID} purpose="question" onConfirmed={vi.fn()} onTyped={vi.fn()} onClose={vi.fn()} /></StoreProvider></LocaleProvider>);
  try {
    fireEvent.click(screen.getByRole("button", { name: "Use camera" }));
    expect(await screen.findByText(copy!)).toBeTruthy(); expect(uploads).toHaveLength(0); expect(screen.queryByLabelText("Live camera preview")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Choose a photo instead", exact: true })); expect(choose).toHaveBeenCalledTimes(1);
    const bytes = new Uint8Array(readFileSync(path.resolve(import.meta.dirname, "../gallery/photo-source-fixture.jpg")));
    fireEvent.change(view.container.querySelector('input[type="file"]')!, { target: { files: [new File([bytes], "synthetic.jpg", { type: "image/jpeg" })] } });
    await waitFor(() => expect(crops).toHaveLength(1));
    expect(uploads).toHaveLength(1); expect(uploads[0]).toMatchObject({ source: "photo_file", purpose: "question" }); expect(uploads[0]?.bytes).toEqual(bytes);
    expect(crops[0]).toMatchObject({ preview_only: true }); expect(screen.getByRole("button", { name: "Crop corner 1" })).toBeTruthy();
    expect(screen.queryByText(copy!)).toBeNull();
  } finally { view.unmount(); session.close(); }
});
