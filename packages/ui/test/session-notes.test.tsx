import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { EMPTY_SESSION_NOTES, type SessionNotesView } from "@jana/client-core";
import { NOTE } from "../../client-core/test/notescore.js";
import { SessionNotesContent } from "../src/learn/SessionNotes.js";
afterEach(cleanup);
function show(flags: Partial<SessionNotesView> = {}) {
  const actions = { onSearch: vi.fn(), onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn(), onPrivate: vi.fn(), onDelete: vi.fn(), onReference: vi.fn(async () => true), onExport: vi.fn() };
  render(<SessionNotesContent view={{ ...EMPTY_SESSION_NOTES, status: "ready", notes: [NOTE], ...flags }} subject={() => "Physics"} kc={() => "Speed"} actions={actions} />);
  return actions;
}
test("uxs52_reference_opens_turn", () => {
  const opened = { ...NOTE, statements: [...NOTE.statements, { section: "method", text: "Unsupported assertion" } as never] };
  const actions = show({ opened });
  expect(screen.getByText("Divide distance by time.")).toBeTruthy();
  expect(screen.queryByText("Unsupported assertion")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Open source turn" }));
  expect(actions.onReference).toHaveBeenCalledWith(NOTE.statements[0]!.reference);
  fireEvent.click(screen.getByRole("button", { name: "Export note" })); expect(actions.onExport).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Delete note" })); expect(actions.onDelete).toHaveBeenCalledWith(NOTE.note_id);
});
test("uxs52_private_note_confirm: title and statements stay hidden until confirmation", () => {
  const actions = show({ notes: [{ ...NOTE, private: true }] });
  expect(screen.queryByText(NOTE.title!)).toBeNull(); expect(screen.queryByText("Divide distance by time.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Open note" }));
  expect(actions.onOpen).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" })); expect(actions.onOpen).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Open note" }));
  fireEvent.click(screen.getByRole("button", { name: "Yes, open it" })); expect(actions.onOpen).toHaveBeenCalledWith(NOTE.note_id, true);
});
test("generation status leaves the rest of the notes list usable", () => {
  const actions = show({ notes: [{ ...NOTE, state: "writing" }, { ...NOTE, note_id: "snt_00000000000000000000000091", title: "Another note" }] });
  expect(screen.getByText("Writing your notes…")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Another note" })); expect(actions.onOpen).toHaveBeenCalled();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "distance" } }); expect(actions.onSearch).toHaveBeenCalledWith("distance");
});

test("uxs52_notes_states_gallery", async () => {
  const { STATES, GalleryView, DECLARED } = await import("../gallery/index.js");
  const scenes = STATES.filter((s) => s.component === "SessionNotes");
  for (const state of DECLARED.SessionNotes ?? []) {
    for (const theme of ["light", "dark"]) {
      const fixture = scenes.find((s) => s.state === state && s.context.theme === theme);
      expect(fixture, `${state} ${theme}`).toBeDefined();
      const shown = render(<GalleryView state={fixture!} />);
      expect(shown.container.textContent?.length).toBeGreaterThan(0);
      cleanup();
    }
  }
});
