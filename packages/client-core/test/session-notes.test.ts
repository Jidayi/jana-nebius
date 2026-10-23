import { expect, test } from "vitest";
import { EMPTY_SESSION_NOTES, SessionNotesController, readSessionNote, sessionNoteText } from "../src/session-notes.js";
import { ProfileController } from "../src/profiles.js";
import { StoreHolder } from "../src/session.js";
import { PROFILES } from "./profilecore.js";
import { NOTE, notesCore } from "./notescore.js";

test("notes are redacted while private and discard statements without a source", () => {
  const malformed = { ...NOTE, statements: [...NOTE.statements, { section: "method", text: "Unsupported" }] };
  expect(readSessionNote(malformed).statements).toEqual(NOTE.statements);
  expect(readSessionNote({ ...malformed, private: true })).toMatchObject({ title: null, statements: [], kc_ids: [] });
  expect(readSessionNote({ ...NOTE, private: true }, true).statements).toEqual(NOTE.statements);
  expect(sessionNoteText(NOTE)).toContain(NOTE.statements[0]!.reference.turn_id);
});
test("local notes open, mark private, search and delete through the active profile", async () => {
  const fake = notesCore(), profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const notes = new SessionNotesController(profiles); await notes.load();
  expect(notes.getView().notes).toEqual([NOTE]);
  expect(await notes.act(NOTE.note_id, "open")).toBe(true);
  await notes.act(NOTE.note_id, "private"); expect(notes.getView().opened).toBeNull();
  await notes.load("distance"); expect(notes.getView().notes).toEqual([]);
  await notes.load(""); expect(notes.getView().notes[0]?.title).toBeNull();
  expect(await notes.act(NOTE.note_id, "open", false)).toBe(false);
  expect(await notes.act(NOTE.note_id, "open", true)).toBe(true);
  await notes.act(NOTE.note_id, "delete"); expect(notes.getView().notes).toEqual([]);
});
test("profile clearing also drops private opened text and late responses", async () => {
  const fake = notesCore(), profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const notes = new SessionNotesController(profiles); const reading = notes.load();
  await profiles.unlock(PROFILES[1]!.profile_id); await reading;
  expect(notes.getView()).toEqual(EMPTY_SESSION_NOTES);
});
