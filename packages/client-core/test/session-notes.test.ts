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
test("ending a session clears an old search and opens only that session's note", async () => {
  const fake = notesCore(), profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const notes = new SessionNotesController(profiles);
  await notes.load("unmatched");
  expect(await notes.end(NOTE.session_id)).toBe(true);
  expect(notes.getView()).toMatchObject({ query: "", opened: NOTE });
  expect(fake.requests.map((r) => r.path)).toEqual([`/v1/sessions/${NOTE.session_id}/end`, `/v1/session-notes/${NOTE.note_id}/open`]);
  expect(await notes.end(PROFILES[1]!.session_id)).toBe(true);
  expect(notes.getView().opened).toBeNull();
});
test("ending a session never confirms a private note automatically", async () => {
  const fake = notesCore(), profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  fake.rows.get(PROFILES[0]!.profile_id)![0]!.private = true;
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const notes = new SessionNotesController(profiles);
  expect(await notes.end(NOTE.session_id)).toBe(true);
  expect(notes.getView()).toMatchObject({ opened: null, notes: [{ title: null, kc_ids: [], statements: [] }] });
  expect(fake.requests).toHaveLength(1);
});
test("switching profiles while ending a session cannot open the previous student's note", async () => {
  const fake = notesCore();
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const fetcher: typeof fetch = async (input, init) => {
    const response = await fake.fetch(input, init);
    if (new URL(String(input)).pathname.endsWith("/end")) await pending;
    return response;
  };
  const profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fetcher });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const notes = new SessionNotesController(profiles), ending = notes.end(NOTE.session_id);
  await profiles.unlock(PROFILES[1]!.profile_id);
  release();
  expect(await ending).toBe(false);
  expect(notes.getView()).toEqual(EMPTY_SESSION_NOTES);
  expect(fake.requests.some((r) => r.path.endsWith("/open"))).toBe(false);
});
test("a notes refresh failure does not misreport a successfully ended session", async () => {
  const fake = notesCore();
  const fetcher: typeof fetch = (input, init) => new URL(String(input)).pathname === "/v1/session-notes"
    ? Promise.reject(new Error("Offline")) : fake.fetch(input, init);
  const profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fetcher });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const notes = new SessionNotesController(profiles);
  expect(await notes.end(NOTE.session_id)).toBe(true);
  expect(notes.getView()).toMatchObject({ status: "failed", opened: null });
});
test("closing notes during the end-session refresh prevents a late automatic open", async () => {
  const fake = notesCore();
  let release!: () => void, fetching!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const started = new Promise<void>((resolve) => { fetching = resolve; });
  const fetcher: typeof fetch = async (input, init) => {
    const response = await fake.fetch(input, init);
    if (new URL(String(input)).pathname === "/v1/session-notes") { fetching(); await pending; }
    return response;
  };
  const profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fetcher });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const notes = new SessionNotesController(profiles), ending = notes.end(NOTE.session_id);
  await started; notes.close(); release();
  expect(await ending).toBe(true);
  expect(notes.getView().opened).toBeNull();
  expect(fake.requests.some((r) => r.path.endsWith("/open"))).toBe(false);
});
