import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { typedCapture, type SessionController, type SpeechController, type SpeechView } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
import { Composer } from "../src/composer/Composer.js";
import { SpeechToolsProvider } from "../src/voice/SpeechTools.js";
import { StudyNotes } from "../src/voice/StudyNotes.js";
import { ReadAloud } from "../src/voice/SpeechTools.js";
import { PartView, TurnView } from "../src/transcript/Turn.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(cleanup);
function speech() {
  let view: SpeechView = { available: true, partId: null, reading: false, text: "", charIndex: 0,
    dictation: "idle", draft: null, error: null };
  const listeners = new Set<() => void>();
  const set = (change: Partial<SpeechView>) => { view = { ...view, ...change }; for (const listener of listeners) listener(); };
  const tools = { listNotes: vi.fn(async () => ({ notes: [] })),
    saveNote: vi.fn(async (text: string) => ({ note_id: "nt_saved", text, source: "voice", created_at: 0, updated_at: 0 })),
    deleteNote: vi.fn(async () => undefined), discardDraft: vi.fn(), hasPack: true, canDictate: true, subscribe: (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); },
    getState: () => view, read: vi.fn(async () => undefined), stopReading: vi.fn(),
    beginDictation: vi.fn(async () => undefined), endDictation: vi.fn(), cancelDictation: vi.fn(),
    confirmDraft: vi.fn(async (draft, text: string) => ({ ...draft, text, status: "confirmed",
      confirmation: { confirmed: true, method: "sent" } })),
    takeDraft: vi.fn(() => { const draft = view.draft; set({ dictation: "idle", draft: null }); return draft; }) };
  return { tools, controller: tools as unknown as SpeechController, set };
}

describe("read-aloud and composer dictation", () => {
  it("shows read-aloud only for completed tutor text and never for a candidate", () => {
    const f = new Fixture(), s = speech();
    f.startTurn(); const part = f.text("Accepted tutor message.");
    f.render(<SpeechToolsProvider controller={s.controller}><PartView partId={part} /></SpeechToolsProvider>);
    expect(screen.queryByRole("button", { name: "Read aloud" })).toBeNull();
    f.end();
    fireEvent.click(screen.getByRole("button", { name: "Read aloud" }));
    expect(s.tools.read).toHaveBeenCalledWith(part);
  });
  it("test_uxs14_reply_action_row: a finished reply ends in one row of icon buttons and its timing", () => {
    const f = new Fixture(), s = speech();
    const turn = f.startTurn(); const part = f.text("A settled tutor reply."); f.end("complete", 4000);
    const session = { commands: {} } as unknown as SessionController;
    render(<LocaleProvider locale="en"><RegistryProvider registry={defaultRegistry()}><StoreProvider holder={f.holder} session={session}>
      <SpeechToolsProvider controller={s.controller}><TurnView turnId={turn} /></SpeechToolsProvider>
    </StoreProvider></RegistryProvider></LocaleProvider>);
    const row = document.querySelector<HTMLElement>("[data-reply-actions]")!;
    expect(row).not.toBeNull();
    // One Read aloud for the reply (in the row, not again under the text), Report a problem, then the timing as text.
    expect(screen.getAllByRole("button", { name: "Read aloud" })).toHaveLength(1);
    const read = row.querySelector<HTMLElement>("button[aria-label='Read aloud']")!;
    const report = row.querySelector<HTMLElement>("button[aria-label='Report a problem']")!;
    expect(read).not.toBeNull();
    expect(report).not.toBeNull();
    for (const button of [read, report]) {
      expect(button.querySelector("svg")).not.toBeNull(); // an icon, its words the name and the hover or focus label
      expect((button.textContent ?? "").trim()).toBe("");
    }
    const timing = row.querySelector("[data-turn-footer]")!;
    expect(timing.textContent).toBe("Worked for 4 s");
    expect(timing.className).toContain("text-faint");
    expect([...row.children].indexOf(timing as Element)).toBe(row.children.length - 1);
    fireEvent.click(read);
    expect(s.tools.read).toHaveBeenCalledWith(part);
    fireEvent.click(report);
    expect(screen.getByRole("group", { name: "What's the problem?" })).toBeTruthy();
  });
  it("inp39_confirm_before_send", async () => {
    const f = new Fixture(), s = speech(), sendCapture = vi.fn();
    const session = { sendCapture } as unknown as SessionController;
    render(<LocaleProvider locale="en"><StoreProvider holder={f.holder} session={session}>
      <SpeechToolsProvider controller={s.controller}><Composer sessionId={SESSION} /></SpeechToolsProvider>
    </StoreProvider></LocaleProvider>);
    await screen.findByRole("textbox");
    const draft = { ...typedCapture("Please explain this question", { sessionId: SESSION, purpose: "question", confirmed: false }),
      source: "voice" as const, status: "awaiting_confirmation" as const };
    act(() => s.set({ dictation: "review", draft }));
    await waitFor(() => expect(screen.getByRole("textbox").textContent).toContain(draft.text));
    expect(sendCapture).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("Nothing has been sent yet");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sendCapture).toHaveBeenCalledWith(expect.objectContaining({ source: "voice", text: draft.text,
      status: "confirmed", confirmation: expect.objectContaining({ confirmed: true, method: "sent" }) }), "ask"));
  });
  it("blocks sending while listening and uses a separate keyboard dictation control", async () => {
    const f = new Fixture(), s = speech(), sendCapture = vi.fn();
    render(<LocaleProvider locale="en"><StoreProvider holder={f.holder} session={{ sendCapture } as unknown as SessionController}>
      <SpeechToolsProvider controller={s.controller}><Composer sessionId={SESSION} /></SpeechToolsProvider>
    </StoreProvider></LocaleProvider>);
    const editor = await screen.findByRole("textbox");
    fireEvent.keyDown(editor, { code: "KeyM", ctrlKey: true });
    expect(s.tools.beginDictation).toHaveBeenCalledWith("question");
    fireEvent.keyUp(editor, { code: "KeyM" }); expect(s.tools.endDictation).toHaveBeenCalled();
    act(() => s.set({ dictation: "listening" }));
    expect(screen.getByRole("button", { name: "Send" }).hasAttribute("disabled")).toBe(true);
    fireEvent.keyDown(editor, { key: "Enter", code: "Enter" });
    expect(sendCapture).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel dictation" }));
    expect(s.tools.cancelDictation).toHaveBeenCalledOnce();
  });
  it("keeps the editable draft when confirmation fails and prevents duplicate confirmation", async () => {
    const f = new Fixture(), s = speech(), sendCapture = vi.fn();
    let reject!: (reason: Error) => void;
    s.tools.confirmDraft.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
    render(<LocaleProvider locale="en"><StoreProvider holder={f.holder} session={{ sendCapture } as unknown as SessionController}>
      <SpeechToolsProvider controller={s.controller}><Composer sessionId={SESSION} /></SpeechToolsProvider>
    </StoreProvider></LocaleProvider>);
    await screen.findByRole("textbox");
    const draft = { ...typedCapture("Keep my edited draft", { sessionId: SESSION, confirmed: false }),
      source: "voice" as const, status: "awaiting_confirmation" as const };
    act(() => s.set({ dictation: "review", draft }));
    await waitFor(() => expect(screen.getByRole("textbox").textContent).toContain(draft.text));
    const send = screen.getByRole("button", { name: "Send" });
    fireEvent.click(send); fireEvent.click(send);
    expect(s.tools.confirmDraft).toHaveBeenCalledOnce();
    await act(async () => reject(new Error("offline")));
    expect(sendCapture).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox").textContent).toContain(draft.text);
    expect(send.hasAttribute("disabled")).toBe(false);
    fireEvent.click(send);
    await waitFor(() => expect(sendCapture).toHaveBeenCalledOnce());
  });
  it("ignores a confirmation completed after switching session controllers", async () => {
    const f = new Fixture(), s = speech(), oldSend = vi.fn(), nextSend = vi.fn();
    let resolve!: (value: Awaited<ReturnType<typeof s.tools.confirmDraft>>) => void;
    s.tools.confirmDraft.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const oldSession = { sendCapture: oldSend } as unknown as SessionController;
    const nextSession = { sendCapture: nextSend } as unknown as SessionController;
    const content = (session: SessionController) => <LocaleProvider locale="en"><StoreProvider holder={f.holder} session={session}>
      <SpeechToolsProvider controller={s.controller}><Composer sessionId={SESSION} /></SpeechToolsProvider>
    </StoreProvider></LocaleProvider>;
    const page = render(content(oldSession));
    await screen.findByRole("textbox");
    const draft = { ...typedCapture("Draft from the old session", { sessionId: SESSION, confirmed: false }),
      source: "voice" as const, status: "awaiting_confirmation" as const };
    act(() => s.set({ dictation: "review", draft }));
    await waitFor(() => expect(screen.getByRole("textbox").textContent).toContain(draft.text));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    page.rerender(content(nextSession));
    await act(async () => resolve({ ...draft, status: "confirmed", confirmation: { confirmed: true, method: "sent" } }));
    expect(oldSend).not.toHaveBeenCalled(); expect(nextSend).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox").textContent).toContain(draft.text);
  });

});


it("dictated notes stay editable and unsaved until Save, then offer owned read-aloud and deletion", async () => {
  const s = speech();
  render(<LocaleProvider locale="en"><SpeechToolsProvider controller={s.controller}><StudyNotes /></SpeechToolsProvider></LocaleProvider>);
  await screen.findByRole("textbox", { name: "Note draft" });
  const draft = { ...typedCapture("Revise units tomorrow", { sessionId: SESSION, purpose: "question", confirmed: false }),
    source: "voice" as const, status: "awaiting_confirmation" as const };
  act(() => s.set({ dictation: "review", draft }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Note draft" }).textContent).toContain(draft.text));
  expect(s.tools.saveNote).not.toHaveBeenCalled(); expect(s.tools.confirmDraft).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save note" }));
  await waitFor(() => expect(s.tools.saveNote).toHaveBeenCalledWith(draft.text, draft));
  fireEvent.click(await screen.findByRole("button", { name: "Read aloud" }));
  expect(s.tools.read).toHaveBeenCalledWith({ kind: "note", note_id: "nt_saved" });
  fireEvent.click(screen.getByRole("button", { name: "Delete note" }));
  await waitFor(() => expect(s.tools.deleteNote).toHaveBeenCalledWith("nt_saved"));
});

it("test_d102_private_note_opens_after_the_confirm_step: listed without its text, opened only after confirming", async () => {
  const s = speech();
  const hidden = { note_id: "nt_private", text: null, source: "typed", created_at: 0, updated_at: 0, private: true };
  const tools = s.tools as typeof s.tools & { openNote: ReturnType<typeof vi.fn>; markNotePrivate: ReturnType<typeof vi.fn> };
  tools.listNotes.mockImplementation(async () => ({ notes: [hidden] }) as never);
  tools.openNote = vi.fn(async () => ({ ...hidden, text: "Circuits before Friday" }));
  tools.markNotePrivate = vi.fn(async () => ({ note_id: "nt_private", text: "Circuits before Friday", source: "typed", created_at: 0, updated_at: 0 }));
  render(<LocaleProvider locale="en"><SpeechToolsProvider controller={s.controller}><StudyNotes /></SpeechToolsProvider></LocaleProvider>);
  await screen.findByText("This note is private.");
  expect(screen.queryByText("Circuits before Friday")).toBeNull();
  expect(screen.queryByRole("button", { name: "Read aloud" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Open note" }));
  expect(tools.openNote).not.toHaveBeenCalled(); // the confirm step first
  screen.getByText("This note is marked private. Open it now?");
  fireEvent.click(screen.getByRole("button", { name: "Yes, open it" }));
  await screen.findByText("Circuits before Friday");
  expect(tools.openNote).toHaveBeenCalledWith("nt_private");
  fireEvent.click(screen.getByRole("button", { name: "Remove private mark" }));
  await waitFor(() => expect(tools.markNotePrivate).toHaveBeenCalledWith("nt_private", false));
  await screen.findByRole("button", { name: "Mark as private" });
});

it("uses the same editable confirmation flow in Home Ask and reports successful explicit submission", async () => {
  const f = new Fixture(), s = speech(), sendCapture = vi.fn(), sent = vi.fn();
  f.startTurn(); f.end(); // Home Ask must start a question even when this session has previous turns.
  render(<LocaleProvider locale="en"><StoreProvider holder={f.holder} session={{ sendCapture } as unknown as SessionController}>
    <SpeechToolsProvider controller={s.controller}><Composer sessionId={SESSION} asking onSent={sent} /></SpeechToolsProvider>
  </StoreProvider></LocaleProvider>);
  await screen.findByRole("textbox");
  const draft = { ...typedCapture("Explain acceleration", { sessionId: SESSION, purpose: "question", confirmed: false }), source: "voice" as const, status: "awaiting_confirmation" as const };
  act(() => s.set({ dictation: "review", draft }));
  await waitFor(() => expect(screen.getByRole("textbox").textContent).toContain(draft.text));
  expect(sent).not.toHaveBeenCalled(); expect(sendCapture).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(sent).toHaveBeenCalledOnce());
  expect(sendCapture).toHaveBeenCalledWith(expect.objectContaining({ text: draft.text, source: "voice" }), "ask");
});

it("stops an owned lesson read when navigation replaces its source", () => {
  const s = speech(), source = { kind: "lesson_block" as const, lesson_id: "lesson", version: "1.0.0", block_index: 0 };
  const result = render(<LocaleProvider locale="en"><SpeechToolsProvider controller={s.controller}><ReadAloud source={source} /></SpeechToolsProvider></LocaleProvider>);
  act(() => s.set({ partId: JSON.stringify(source), reading: true }));
  result.unmount(); expect(s.tools.stopReading).toHaveBeenCalledOnce();
});


it("retains a note after a failed Save and prevents concurrent duplicate saves", async () => {
  const s = speech();
  let reject!: (reason: Error) => void;
  s.tools.saveNote.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  render(<LocaleProvider locale="en"><SpeechToolsProvider controller={s.controller}><StudyNotes /></SpeechToolsProvider></LocaleProvider>);
  await screen.findByRole("textbox", { name: "Note draft" });
  const draft = { ...typedCapture("Keep this revision note", { sessionId: SESSION, confirmed: false }),
    source: "voice" as const, status: "awaiting_confirmation" as const };
  act(() => s.set({ dictation: "review", draft }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Note draft" }).textContent).toContain(draft.text));
  const save = screen.getByRole("button", { name: "Save note" });
  act(() => { fireEvent.click(save); fireEvent.click(save); });
  expect(s.tools.saveNote).toHaveBeenCalledOnce();
  await act(async () => reject(new Error("disk unavailable")));
  expect(screen.getByRole("textbox", { name: "Note draft" }).textContent).toContain(draft.text);
  fireEvent.click(save);
  await waitFor(() => expect(s.tools.saveNote).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Note draft" }).textContent).toBe(""));
});
