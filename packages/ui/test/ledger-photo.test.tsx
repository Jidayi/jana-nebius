import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { EntryEditor, type EntryHandle } from "../src/composer/EntryEditor.js";
import { PhotoCapture } from "../src/composer/PhotoCapture.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
import { StoreHolder } from "@jana/client-core";
afterEach(cleanup);

test("keyboard-only journal entry adds a row, preserves three lines and submits structured content", async () => {
  const ref = createRef<EntryHandle>(); const submitted = vi.fn(() => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} label="Accounting answer" placeholder="Write here" accounting onSubmit={submitted} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Maths keyboard" }));
  fireEvent.click(screen.getByRole("button", { name: "Journal" }));
  const rows = [["Equipment", "5000", ""], ["Cash", "", "2500"], ["Payables", "", "2500"]];
  for (const [index, [account, dr, cr]] of rows.entries()) {
    await screen.findByLabelText(`Row ${index + 1}, Particulars`);
    fireEvent.change(screen.getByLabelText(`Row ${index + 1}, Particulars`), { target: { value: account } });
    fireEvent.change(screen.getByLabelText(`Row ${index + 1}, Dr`), { target: { value: dr } });
    fireEvent.change(screen.getByLabelText(`Row ${index + 1}, Cr`), { target: { value: cr } });
    if (index < 2) fireEvent.keyDown(screen.getByLabelText(`Row ${index + 1}, Cr`), { key: "Tab" });
  }
  act(() => ref.current?.submit());
  expect(submitted).toHaveBeenCalledTimes(1);
  expect(ref.current?.blocks()[0]).toMatchObject({ type: "ledger_table", rows: [["", "Equipment", "", "5000", ""], ["", "Cash", "", "", "2500"], ["", "Payables", "", "", "2500"]] });
  expect(await screen.findByText("Dr total 5000; Cr total 5000 (USD)")).toBeDefined();
});

test("journal conversion is offered explicitly and invalid amount cells keep the table draft", async () => {
  const ref = createRef<EntryHandle>(); const sent = vi.fn(() => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} label="Accounting answer" placeholder="Write here" accounting onSubmit={sent} /></LocaleProvider>);
  fireEvent.paste(screen.getByRole("textbox", { name: "Accounting answer" }), { clipboardData: { getData: (format: string) => format === "text/plain" ? "Dr Cash 5000; Cr Sales 5000" : "" } });
  expect(screen.queryByRole("table")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Make this a journal?" }));
  await screen.findByLabelText("Row 1, Dr");
  fireEvent.change(screen.getByLabelText("Row 1, Dr"), { target: { value: "five thousand" } });
  act(() => ref.current?.submit());
  expect(sent).not.toHaveBeenCalled(); expect(screen.getByRole("table")).toBeDefined();
});

test("closing camera preview releases every media track, including late permission responses", async () => {
  let resolve: (value: MediaStream) => void = () => undefined;
  const stop = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn(async () => new Promise<MediaStream>((r) => { resolve = r; })) } });
  const view = render(<LocaleProvider locale="en"><StoreProvider holder={new StoreHolder()} session={null}><PhotoCapture sessionId="ses_synthetic" purpose="question" onConfirmed={vi.fn()} onTyped={vi.fn()} onClose={vi.fn()} /></StoreProvider></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Use camera" }));
  view.unmount();
  await act(async () => resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream));
  expect(stop).toHaveBeenCalledTimes(1);
});


test("camera permission finishing after focus loss cannot reopen the camera", async () => {
  let resolve: (value: MediaStream) => void = () => undefined;
  const stop = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn(async () => new Promise<MediaStream>((r) => { resolve = r; })) } });
  render(<LocaleProvider locale="en"><StoreProvider holder={new StoreHolder()} session={null}><PhotoCapture sessionId="ses_synthetic" purpose="question" onConfirmed={vi.fn()} onTyped={vi.fn()} onClose={vi.fn()} /></StoreProvider></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Use camera" }));
  fireEvent.blur(window);
  await act(async () => resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream));
  expect(stop).toHaveBeenCalledTimes(1);
  expect(screen.queryByLabelText("Live camera preview")).toBeNull();
});

test("an Up next question starts a new problem after an existing conversation", async () => {
  const { Composer } = await import("../src/composer/Composer.js");
  const { Fixture, SESSION } = await import("./harness.js");
  const { SessionController } = await import("@jana/client-core");
  const fixture = new Fixture(); fixture.startTurn(); fixture.end();
  const sent: Record<string, unknown>[] = [];
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, fixture.holder, SESSION, {
    fetch: async (url, init) => {
      if (String(url).endsWith("/captures")) return new Response(JSON.stringify({ captures: [{ capture_id: "cap_synthetic", session_id: SESSION,
        questions: [{ label: "2", selected: false, region_ids: ["rgn_2"] }], regions: [{ region_id: "rgn_2", text: "Find the area" }] }] }));
      if (init?.method === "GET") return new Response(JSON.stringify({ revision: 0, document: { type: "doc" } }));
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      if (String(url).endsWith("/turns")) sent.push(body);
      return new Response(JSON.stringify({ revision: 1, turn_id: "trn_synthetic", message_id: "msg_synthetic" }), { status: 202 });
    },
  });
  try {
    render(<LocaleProvider locale="en"><StoreProvider holder={fixture.holder} session={session}><Composer sessionId={SESSION} /></StoreProvider></LocaleProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "2: Find the area" }));
    expect(sent).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ intent: "ask", content: [{ type: "text", text: "Find the area" }] });
  } finally { session.close(); }
});


test("choosing a photo shows the native outline before reading or creating derivatives", async () => {
  const { SessionController, typedCapture } = await import("@jana/client-core");
  const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const capture = { ...typedCapture("", { sessionId: "ses_synthetic", purpose: "question", confirmed: false }), source: "photo_file" };
  const requests: Record<string, unknown>[] = [];
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, new StoreHolder(), "ses_synthetic", {
    fetch: async (url, init) => {
      if (String(url).endsWith("/crop")) {
        requests.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return new Response(JSON.stringify({ ...capture, outline: [{ x: .1, y: .2 }, { x: .9, y: .2 }, { x: .9, y: .8 }, { x: .1, y: .8 }] }));
      }
      return new Response(JSON.stringify(capture));
    },
  });
  const png = new Uint8Array(24); const header = new DataView(png.buffer);
  header.setUint32(0, 0x89504e47); header.setUint32(4, 0x0d0a1a0a); header.setUint32(16, 900); header.setUint32(20, 700);
  const file = new Blob([png], { type: "image/png" });
  const view = render(<LocaleProvider locale="en"><StoreProvider holder={new StoreHolder()} session={session}><PhotoCapture sessionId="ses_synthetic" purpose="question" file={file} onConfirmed={vi.fn()} onTyped={vi.fn()} onClose={vi.fn()} /></StoreProvider></LocaleProvider>);
  try {
    const corner = await screen.findByRole("button", { name: "Crop corner 1" });
    expect(corner.getAttribute("style")).toContain("10%");
    expect(requests).toMatchObject([{ preview_only: true, rotation: 0 }]);
    expect(screen.queryByText("Is this the question?")).toBeNull();
  } finally { view.unmount(); session.close(); createUrl.mockRestore(); revoke.mockRestore(); }
});

test.each(["photo_file", "photo_paste", "photo_camera"] as const)("uxs13_no_guess_on_bad_photo: %s", async (source) => {
  const { typedCapture } = await import("@jana/client-core");
  const typed = vi.fn(), confirmed = vi.fn(), closed = vi.fn();
  const capture = { ...typedCapture("UNRELIABLE-GUESS", { sessionId: "ses_synthetic", purpose: "question", confirmed: false }), source, status: "unreadable" as const, overall_confidence: 0.1, refusal: { reason: "unreadable" as const } };
  render(<LocaleProvider locale="en"><StoreProvider holder={new StoreHolder()} session={null}><PhotoCapture previewCapture={capture} sessionId="ses_synthetic" purpose="question" onConfirmed={confirmed} onTyped={typed} onClose={closed} /></StoreProvider></LocaleProvider>);
  expect(screen.getByText("I couldn't read this clearly.")).toBeDefined();
  for (const tip of ["Lay the page flat.", "Use more light.", "Move closer so the question fills the frame."]) expect(screen.getByText(tip)).toBeDefined();
  expect(screen.getByRole("button", { name: "Try another photo" })).toBeDefined();
  expect(screen.queryByText("Is this the question?")).toBeNull();
  expect(screen.queryByText("UNRELIABLE-GUESS")).toBeNull();
  expect(screen.queryByRole("button", { name: "Yes, that's it" })).toBeNull();
  expect(screen.queryByRole("textbox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Type it instead" }));
  expect(typed).toHaveBeenCalledWith("");
  expect(confirmed).not.toHaveBeenCalled(); expect(closed).toHaveBeenCalledOnce();
});
