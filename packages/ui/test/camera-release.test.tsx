import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { SessionController, StoreHolder, typedCapture } from "@jana/client-core";
import { PhotoCapture } from "../src/composer/PhotoCapture.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
const SID = `ses_${"0".repeat(26)}`;
const mediaDescriptor = Object.getOwnPropertyDescriptor(navigator, "mediaDevices"), visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.useRealTimers();
  if (mediaDescriptor) Object.defineProperty(navigator, "mediaDevices", mediaDescriptor); else Reflect.deleteProperty(navigator, "mediaDevices");
  if (visibilityDescriptor) Object.defineProperty(document, "visibilityState", visibilityDescriptor); else Reflect.deleteProperty(document, "visibilityState");
});
function mount(permission?: Promise<MediaStream>) {
  vi.useFakeTimers(); const stops = [vi.fn(), vi.fn()], feed = new MediaStream();
  Object.defineProperty(feed, "getTracks", { value: () => stops.map((stop) => ({ stop })) });
  const getUserMedia = vi.fn(async () => permission ?? feed);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia, enumerateDevices: vi.fn(async () => []) } });
  const requests: string[] = [], holder = new StoreHolder();
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, SID, {
    fetch: async (url) => { requests.push(String(url)); return Response.json(typedCapture("", { sessionId: SID, purpose: "question", confirmed: false })); },
  });
  const urls = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-frame"); vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const storage = vi.spyOn(Storage.prototype, "setItem");
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(160 * 120 * 4).fill(255) }) } as unknown as CanvasRenderingContext2D);
  const encode = vi.spyOn(HTMLCanvasElement.prototype, "toBlob");
  function View({ id = SID }: { id?: string }) {
    const [open, setOpen] = useState(true);
    return <LocaleProvider locale="en"><StoreProvider holder={holder} session={session}>{open && <PhotoCapture key={id} sessionId={id} purpose="question" onConfirmed={vi.fn()} onTyped={vi.fn()} onClose={() => setOpen(false)} />}</StoreProvider></LocaleProvider>;
  }
  const view = render(<View />);
  return { ...view, View, stops, feed, getUserMedia, requests, urls, storage, encode, session };
}
const closings = ["cancel", "escape", "unmount", "blur", "pagehide", "hidden", "session"] as const;
type Closing = typeof closings[number];
function close(view: ReturnType<typeof mount>, action: Closing) {
  if (action === "cancel") fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  else if (action === "escape") fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  else if (action === "unmount") view.unmount();
  else if (action === "blur") fireEvent.blur(window);
  else if (action === "pagehide") fireEvent(window, new Event("pagehide"));
  else if (action === "hidden") { Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" }); fireEvent(document, new Event("visibilitychange")); }
  else view.rerender(<view.View id={`ses_${"1".repeat(26)}`} />);
}
test.each(closings)("inp16_camera_released: %s stops every track and drops preview references", async (action) => {
  const view = mount();
  try {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Use camera" })); await Promise.resolve(); });
    const video = screen.getByLabelText("Live camera preview") as HTMLVideoElement;
    expect(video.srcObject).toBe(view.feed);
    Object.defineProperties(video, { videoWidth: { value: 900 }, videoHeight: { value: 700 } });
    expect(view.getUserMedia).toHaveBeenCalledWith({ video: { facingMode: "environment" }, audio: false });
    act(() => vi.advanceTimersByTime(500)); // preview advisory sampling stays in transient canvas memory
    close(view, action);
    expect(view.stops.every((stop) => stop.mock.calls.length === 1)).toBe(true);
    expect(video.srcObject).toBeNull(); expect(screen.queryByLabelText("Live camera preview")).toBeNull();
    act(() => vi.advanceTimersByTime(1000));
    expect(view.requests).toEqual([]); expect(view.urls).not.toHaveBeenCalled(); expect(view.storage).not.toHaveBeenCalled(); expect(view.encode).not.toHaveBeenCalled();
  } finally { view.unmount(); view.session.close(); }
});
test.each(closings)("inp16_camera_released: permission resolving after %s is immediately stopped", async (action) => {
  let resolve: (stream: MediaStream) => void = () => undefined;
  const pending = new Promise<MediaStream>((done) => { resolve = done; }), view = mount(pending);
  try {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Use camera" })); await Promise.resolve(); });
    close(view, action);
    await act(async () => { resolve(view.feed); await Promise.resolve(); });
    expect(view.stops.every((stop) => stop.mock.calls.length === 1)).toBe(true);
    expect(screen.queryByLabelText("Live camera preview")).toBeNull(); expect(view.requests).toEqual([]);
  } finally { view.unmount(); view.session.close(); }
});
test("inp16_camera_released: an encoder finishing after close cannot upload or retain a frame", async () => {
  const view = mount(); let encoded: BlobCallback = () => undefined;
  view.encode.mockImplementation((callback) => { encoded = callback; });
  try {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Use camera" })); await Promise.resolve(); });
    const video = screen.getByLabelText("Live camera preview"); Object.defineProperties(video, { videoWidth: { value: 900 }, videoHeight: { value: 700 } });
    fireEvent.keyDown(video, { key: " " }); expect(view.stops.every((stop) => stop.mock.calls.length === 1)).toBe(true);
    close(view, "cancel");
    await act(async () => { encoded(new Blob(["synthetic captured frame"], { type: "image/jpeg" })); await Promise.resolve(); });
    expect(view.requests).toEqual([]); expect(view.urls).not.toHaveBeenCalled(); expect(view.storage).not.toHaveBeenCalled();
  } finally { view.unmount(); view.session.close(); }
});


test("switching cameras releases the old stream and binds an immediately resolved replacement", async () => {
  const view = mount(), next = new MediaStream(), stop = vi.fn();
  Object.defineProperty(next, "getTracks", { value: () => [{ stop }] });
  const devices = [{ deviceId: "one", label: "First", kind: "videoinput" }, { deviceId: "two", label: "Second", kind: "videoinput" }];
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: view.getUserMedia, enumerateDevices: vi.fn(async () => devices) } });
  try {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Use camera" })); await Promise.resolve(); });
    view.getUserMedia.mockResolvedValueOnce(next);
    await act(async () => { fireEvent.change(screen.getByRole("combobox", { name: "Choose camera" }), { target: { value: "two" } }); await Promise.resolve(); });
    expect(view.stops.every((s) => s.mock.calls.length === 1)).toBe(true);
    expect((screen.getByLabelText("Live camera preview") as HTMLVideoElement).srcObject).toBe(next);
    close(view, "cancel"); expect(stop).toHaveBeenCalledTimes(1);
  } finally { view.unmount(); view.session.close(); }
});
