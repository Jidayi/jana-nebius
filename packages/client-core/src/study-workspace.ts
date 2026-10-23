/** M42: profile-bound source library and study aids, using the local API rather than a browser provider. */
import { isValid, type study_workspace as W } from "@jana/contracts-ts/client";
import { clientId } from "./ids.js";
import type { ProfileController } from "./profiles.js";
import { CommandClient, CommandError } from "./stream/commands.js";
import type { LocalSpeech } from "./speech.js";
import { readSessionNote } from "./session-notes.js";

export type { W as StudyContracts };
export interface StudyWorkspaceView {
  status: "idle" | "loading" | "ready" | "failed";
  sources: W.SourceList["items"]; jobs: W.Job[]; source: W.Source | null; chunks: W.Chunk[]; aids: W.Aid[];
  aid: W.Aid | null; deck: W.Deck | null; quiz: W.QuizView | null; result: W.QuizResult | null;
  cleanupPending: boolean; availableRevisions: number[]; busy: boolean; error: string | null; uploadBytes: number; uploadTotal: number;
  selections: W.SourceSelection[]; notes: { id: string; kind: "session_note" | "dictated_note" | "board_note"; title: string | null; private: boolean }[];
  reading: boolean; spokenClaim: number; canSpeak: boolean;
  followCurrent: boolean;
  topics: W.TopicLinks["items"];
  safetyTemplate?: string | null;
  /** STU-21 My Sets, newest first, with live progress; a private source's sets carry no title until opened. */
  sets: W.StudySet[];
  /** STU-21: the open material's own topics, for the Generate settings. */
  materialTopics: W.MaterialTopics["items"];
  /** STU-22: a request to move the player to a moment of the open recording (a new `seq` each time). */
  playhead: { ms: number; seq: number } | null;
}
export const EMPTY_STUDY: StudyWorkspaceView = { status: "idle", sources: [], jobs: [], source: null, chunks: [], aids: [], aid: null, deck: null, quiz: null, result: null, cleanupPending: false, availableRevisions: [], busy: false, error: null, uploadBytes: 0, uploadTotal: 0, selections: [], notes: [], reading: false, spokenClaim: 0, canSpeak: false, followCurrent: true, topics: [], sets: [], materialTopics: [], playhead: null };
/** The Generate panel's tools (STU-21), in the order the panel shows them. */
export const GENERATE_TOOLS = ["summary", "quiz", "flashcards", "notes", "audio_overview", "lesson_plan"] as const;
export type GenerateTool = (typeof GENERATE_TOOLS)[number];
/** Kinds that draw on every selected source rather than the open one alone. */
const MULTI_SOURCE: readonly string[] = ["notes", "summary", "chat", "lesson_plan"];
function valid<T>(name: string, value: unknown): T {
  if (!isValid(`study/workspace#/$defs/${name}`, value)) throw new CommandError(200, "invalid_reply", false, undefined);
  return value as T;
}
async function sha(data: Uint8Array): Promise<string> {
  const result = await crypto.subtle.digest("SHA-256", new Uint8Array(data).buffer);
  return Array.from(new Uint8Array(result), (b) => b.toString(16).padStart(2, "0")).join("");
}
function base64(data: Uint8Array): string {
  let result = "";
  for (let i = 0; i < data.length; i += 8192) result += String.fromCharCode(...data.subarray(i, i + 8192));
  return btoa(result);
}
export class StudyWorkspaceController {
  private view = EMPTY_STUDY;
  private listeners = new Set<() => void>();
  private sequence = 0;
  private grant: string | null = null;
  private referenceGrants: { sid: string; token: string; expiry: number }[] = [];
  private grantExpires = 0;
  private selection = 0;
  /** The Chat question asked last, until its answer is ready and shown (STU-20). */
  private askedChat: string | null = null;
  private speechGeneration = 0;
  private cancelSpeech: (() => void) | null = null;
  private finishSpeech: ((ok: boolean) => void) | null = null;
  private speechExpiry: ReturnType<typeof setTimeout> | null = null;
  constructor(private readonly profiles: ProfileController, private readonly speech?: LocalSpeech) {
    profiles.onClear(() => { this.stopReading(); this.sequence++; this.selection++; this.referenceGrants = []; this.grant = null; this.grantExpires = 0; this.set({ ...EMPTY_STUDY, canSpeak: speech?.available() ?? false }); });
    if (speech) { this.patch({ canSpeak: speech.available() }); speech.subscribe(() => this.patch({ canSpeak: speech.available() })); }
  }
  getView = (): StudyWorkspaceView => this.view;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private set(view: StudyWorkspaceView): void { this.view = view; for (const fn of this.listeners) fn(); }
  private patch(view: Partial<StudyWorkspaceView>): void { this.set({ ...this.view, ...view }); }
  /** VOC-53, D130: the open source as the voice conversation's place in the Chat tab, with its open grant; null when
   * nothing is open or a private source's grant has lapsed. */
  voicePlace(): { place: "study"; source_id: string; revision: number; open: string } | null {
    const source = this.view.source;
    if (!source) return null;
    const live = this.grant !== null && this.grantExpires > Date.now();
    if (source.private && !live) return null;
    return { place: "study", source_id: source.source_id, revision: source.revision, open: live ? this.grant ?? "" : "" };
  }
  private headers(): Record<string, string> {
    const tokens = this.referenceGrants.filter((g) => g.expiry > Date.now()).map((g) => g.token);
    if (this.grant && this.grantExpires > Date.now()) tokens.unshift(this.grant);
    return tokens.length ? { "X-Study-Open": tokens.slice(0, 8).join(",") } : {};
  }
  private commands(): CommandClient {
    const generation = this.profiles.generation;
    return this.profiles.commands.scoped(() => generation === this.profiles.generation);
  }
  private async allAids(sourceId: string): Promise<W.Aid[]> {
    const commands = this.commands();
    const items: W.Aid[] = []; let cursor: string | null = null;
    do {
      const page: W.AidList = valid("AidList", await commands.get(`/v1/study/aids?source_id=${sourceId}&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, this.headers()));
      items.push(...page.items); cursor = page.next_cursor;
    } while (cursor !== null);
    return items;
  }
  private async mutate<T>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown, headers = this.headers()): Promise<T> {
    const commands = this.commands();
    const stableBody = body && typeof body === "object" ? { ...body } as Record<string, unknown> : body;
    if (stableBody && typeof stableBody === "object") { delete (stableBody as Record<string, unknown>).client_review_id; delete (stableBody as Record<string, unknown>).attempt_id; }
    const hash = await sha(new TextEncoder().encode(JSON.stringify({ method, path, body: stableBody ?? null })));
    const identity = valid<W.RetryIdentity>("RetryIdentity", await commands.post(`/v1/study/retries/${hash}`, {}, clientId()));
    const finalBody = path.endsWith("/reviews") ? { ...(stableBody as object), client_review_id: identity.client_key.replace("cli_", "srv_") } : path.endsWith("/attempts") ? { ...(stableBody as object), attempt_id: identity.client_key.replace("cli_", "sqa_") } : body;
    const value = await commands.request<T>(method, path, finalBody, identity.client_key, headers);
    await commands.delete(`/v1/study/retries/${hash}`, identity.client_key).catch(() => undefined);
    return value;
  }
  private async action(work: (current: () => boolean) => Promise<void>): Promise<void> {
    if (this.view.busy) return;
    const generation = this.profiles.generation, selection = this.selection;
    const current = () => generation === this.profiles.generation && selection === this.selection;
    this.patch({ busy: true, error: null, safetyTemplate: null });
    try { await work(current); }
    catch (error) {
      if (current()) {
        const template = error instanceof CommandError && error.details?.reason === "safety_template" ? error.details.template_id : null;
        const safetyTemplate = typeof template === "string" && ["tpl.distress", "tpl.off_topic", "tpl.graded_work", "tpl.personal_details", "tpl.dangerous_request", "tpl.abusive_language", "tpl.see_trusted_adult"].includes(template) ? template : null;
        const reason = safetyTemplate === "tpl.graded_work" ? "graded_work" : error instanceof CommandError ? String(error.details?.reason ?? error.code) : "unreachable";
        if (reason === "grant_expired") this.close();
        this.patch({ error: reason, safetyTemplate });
      }
    } finally { if (current()) this.patch({ busy: false }); }
  }
  async load(): Promise<void> {
    const generation = this.profiles.generation, seq = ++this.sequence;
    const commands = this.commands();
    if (this.view.status === "idle") this.patch({ status: "loading" });
    try {
      let snapshot = valid<W.StudySnapshot>("StudySnapshot", await commands.get("/v1/study/workspace", this.headers()));
      const sources = [...snapshot.sources.items];
      while (snapshot.sources.next_cursor !== null) {
        snapshot = valid<W.StudySnapshot>("StudySnapshot", await commands.get(`/v1/study/workspace?cursor=${encodeURIComponent(snapshot.sources.next_cursor)}`, this.headers()));
        if (generation !== this.profiles.generation || seq !== this.sequence) return;
        sources.push(...snapshot.sources.items);
      }
      if (generation !== this.profiles.generation || seq !== this.sequence) return;
      if ((this.view.source?.private && this.grantExpires <= Date.now()) || this.referenceGrants.some((g) => g.expiry <= Date.now())) this.close();
      // My Sets is a view over the aids: if it cannot be read, the library still opens with the sets it had.
      let sets = this.view.sets;
      try { sets = valid<W.StudySetList>("StudySetList", await commands.get("/v1/study/sets", this.headers())).items; } catch { /* kept */ }
      if (generation !== this.profiles.generation || seq !== this.sequence) return;
      this.patch({ status: "ready", sources, jobs: snapshot.jobs, cleanupPending: snapshot.cleanup_pending ?? false, sets });
    } catch { if (generation === this.profiles.generation && seq === this.sequence) this.patch({ status: "failed" }); }
  }
  /** STU-21: open a set where it was left: its material, then the aid (a quiz restores its draft answers). */
  async openSet(set: W.StudySet): Promise<void> {
    const first = set.sources[0];
    if (!first) return;
    const listed = this.view.sources.find((s) => s.source_id === first.source_id);
    await this.open(first.source_id, listed && listed.revision !== first.revision ? first.revision : undefined);
    if (this.view.source?.source_id === first.source_id) await this.showAid(set.aid_id);
  }
  /** STU-21: the open material's own topics, all kept by default in the Generate settings. */
  async loadMaterialTopics(): Promise<void> {
    const source = this.view.source;
    if (!source) return;
    const generation = this.profiles.generation, selection = this.selection;
    try {
      const result = valid<W.MaterialTopics>("MaterialTopics", await this.commands().get(`/v1/study/sources/${source.source_id}/material-topics?revision=${source.revision}`, this.headers()));
      if (generation === this.profiles.generation && selection === this.selection) this.patch({ materialTopics: result.items });
    } catch { /* Topics are optional: the settings simply show none. */ }
  }
  /** STU-21: keep a quiz's unsubmitted answers and place, so the set opens where it was left. */
  async saveDraft(answers: Record<string, string>, position: number): Promise<void> {
    const quiz = this.view.quiz;
    if (!quiz || quiz.status !== "ready" || this.view.result) return;
    const draft: W.QuizDraft = { quiz_revision: quiz.revision, position: Math.max(0, Math.min(quiz.items.length - 1, position)), answers: Object.entries(answers).filter(([, a]) => a.trim()).map(([item_id, answer]) => ({ item_id, answer })) };
    try {
      const saved = valid<W.QuizDraft>("QuizDraft", await this.mutate("PUT", `/v1/study/quizzes/${quiz.quiz_id}/draft`, draft));
      if (this.view.quiz?.quiz_id === quiz.quiz_id) this.patch({ quiz: { ...this.view.quiz, draft: saved } });
    } catch { /* A draft is a convenience: the answers on screen stay as they are. */ }
  }
  /** STU-22: the open recording's own bytes for the player; they never leave the device. */
  async loadMedia(): Promise<Blob | null> {
    const source = this.view.source;
    if (!source || source.kind !== "recording") return null;
    let result: Blob | null = null;
    await this.action(async (current) => {
      const blob = await this.commands().request<Blob>("GET", `/v1/study/sources/${source.source_id}/media?revision=${source.revision}`, undefined, null, this.headers(), true);
      if (current()) result = blob;
    });
    return result;
  }
  /** STU-22: move the player to a moment of the open recording (a chapter, a transcript line, a citation). */
  seek(ms: number): void { this.patch({ playhead: { ms: Math.max(0, ms), seq: (this.view.playhead?.seq ?? 0) + 1 } }); }
  close(): void {
    this.stopReading();
    const headers = this.headers(), ids = new Set(this.referenceGrants.map((g) => g.sid));
    if (this.view.source) ids.add(this.view.source.source_id);
    for (const id of ids) void this.commands().delete(`/v1/study/sources/${id}/open`, clientId(), headers).catch(() => undefined);
    this.referenceGrants = []; this.selection++; this.grant = null; this.grantExpires = 0; this.patch({ source: null, chunks: [], aids: [], aid: null, deck: null, quiz: null, result: null, selections: [], topics: [], materialTopics: [], playhead: null, error: null, busy: false }); }
  async open(id: string, revision?: number): Promise<void> {
    this.close();
    await this.action(async (current) => {
      const opened = valid<W.OpenedSource>("OpenedSource", await this.commands().post(`/v1/study/sources/${id}/open`, { confirm: true, ...(revision ? { revision } : {}) }, clientId()));
      if (!current()) return;
      this.grant = opened.open_token; this.grantExpires = Date.parse(opened.expires_at);
      const chunks: W.Chunk[] = [];
      let cursor: string | null = null;
      do {
        const result: W.ChunkList = valid("ChunkList", await this.commands().get(`/v1/study/sources/${id}/content?revision=${opened.source.revision}&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, this.headers()));
        if (!current()) return;
        chunks.push(...result.items); cursor = result.next_cursor;
      } while (cursor !== null);
      const aids = await this.allAids(id);
      if (current()) this.patch({ source: opened.source, followCurrent: revision === undefined, selections: [{ source_id: id, revision: opened.source.revision }], availableRevisions: opened.available_revisions ?? [opened.source.revision], chunks, aids });
    });
  }
  async addText(title: string, text: string): Promise<void> {
    let source: W.Source | null = null;
    await this.action(async (current) => {
      const result = valid<W.Source>("Source", await this.mutate("POST", "/v1/study/sources", { kind: "text", title, text }));
      if (current()) source = result;
    });
    if (source) { await this.load(); await this.open((source as W.Source).source_id); }
  }
  async upload(file: File, existing?: W.Source, preferCloud = false, replacement = false): Promise<void> {
    let source: W.Source | null = null;
    await this.action(async (current) => {
      if (file.size === 0 || file.size > 100 * 1024 * 1024) throw new CommandError(422, "source_too_large", false, undefined);
      const suffix = file.name.split(".").at(-1)?.toLowerCase();
      const kind = suffix === "pdf" ? "pdf" : ["pptx", "odp"].includes(suffix ?? "") ? "slides" : ["txt", "md", "docx", "odt"].includes(suffix ?? "") ? "document" : ["jpg", "jpeg", "png", "webp"].includes(suffix ?? "") ? "photo" : ["wav", "mp3", "m4a", "mp4", "webm", "ogg", "flac", "aac", "mov", "mkv", "avi"].includes(suffix ?? "") ? "recording" : null;
      if (!kind) throw new CommandError(422, "unsupported_format", false, undefined);
      this.patch({ uploadBytes: 0, uploadTotal: file.size });
      const data = new Uint8Array(await file.arrayBuffer()), hash = await sha(data);
      if (!current()) return;
      if (existing && !replacement && existing.sha256 !== hash) throw new CommandError(422, "corrupt_source", false, undefined);
      const metadata = { kind, file_name: file.name, mime_type: file.type || "application/octet-stream", byte_length: file.size, sha256: hash };
      const result = replacement && existing ? valid<W.Source>("Source", await this.mutate("POST", `/v1/study/sources/${existing.source_id}/revisions`, { expected_revision: existing.revision, file_name: file.name, mime_type: metadata.mime_type, byte_length: file.size, sha256: hash })) : existing ?? valid<W.Source>("Source", await this.mutate("POST", "/v1/study/sources", { kind, file_name: file.name, mime_type: file.type || "application/octet-stream", byte_length: file.size, sha256: hash }));
      if (!current()) return;
      if (replacement && result.private) {
        const grant = valid<W.OpenedSource>("OpenedSource", await this.commands().post(`/v1/study/sources/${result.source_id}/open`, { confirm: true, revision: result.revision }, clientId()));
        if (!current()) return;
        this.referenceGrants.push({ sid: result.source_id, token: grant.open_token, expiry: Date.parse(grant.expires_at) });
      }
      for (let offset = 0; offset < data.length; offset += 1024 * 1024) {
        const chunk = data.subarray(offset, offset + 1024 * 1024), chunkHash = await sha(chunk);
        if (!current()) return;
        const receipt = valid<W.UploadReceipt>("UploadReceipt", await this.mutate("PUT", `/v1/study/sources/${result.source_id}/chunks/${offset / (1024 * 1024)}`, { offset, sha256: chunkHash, data_base64: base64(chunk) }));
        if (!current()) return;
        this.patch({ uploadBytes: receipt.received_bytes });
      }
      const job = valid<W.Job>("Job", await this.mutate("POST", "/v1/study/jobs", { kind: "extract", execution: preferCloud ? "prefer_cloud" : "local", sources: [{ source_id: result.source_id, revision: result.revision }] }));
      if (current()) { source = result; this.patch({ jobs: [job, ...this.view.jobs] }); }
    });
    if (source) { await this.load(); await this.open((source as W.Source).source_id); }
  }
  /** Start a generation job; `settings` are the Generate panel's choices for that tool (STU-21). */
  async generate(kind: W.AidKind, count = 10, confirmReadableOnly = false, preferCloud = false, prompt?: string, settings?: W.GenerateSettings): Promise<void> {
    const source = this.view.source;
    if (!source) return;
    await this.action(async (current) => {
      const body = { kind, execution: preferCloud ? "prefer_cloud" : "local", ...(confirmReadableOnly ? { confirm_readable_only: true } : {}), sources: MULTI_SOURCE.includes(kind) ? this.view.selections : [{ source_id: source.source_id, revision: source.revision }], ...(["flashcards", "quiz"].includes(kind) ? { count } : {}), ...(kind === "chat" ? { prompt: prompt?.trim() } : {}), ...(settings && Object.keys(settings).length > 0 ? { settings } : {}) };
      const job = valid<W.Job>("Job", await this.mutate("POST", "/v1/study/jobs", body));
      if (kind === "chat") this.askedChat = job.job_id; // its answer opens when it is ready, as a chat reply would
      if (current()) this.patch({ jobs: [job, ...this.view.jobs] });
    });
  }
  async jobAction(id: string, action: "cancel" | "retry" | "resume"): Promise<void> {
    await this.action(async (current) => {
      const job = valid<W.Job>("Job", await this.mutate("POST", `/v1/study/jobs/${id}/actions`, { action }));
      if (current()) this.patch({ jobs: this.view.jobs.map((j) => j.job_id === id ? job : j) });
    });
  }
  async selectExtra(id: string): Promise<void> {
    if (id === this.view.source?.source_id) return;
    if (this.view.selections.some((s) => s.source_id === id)) { this.patch({ selections: this.view.selections.filter((s) => s.source_id !== id) }); return; }
    if (this.view.selections.length >= 8) return;
    await this.action(async (current) => {
      const opened = valid<W.OpenedSource>("OpenedSource", await this.commands().post(`/v1/study/sources/${id}/open`, { confirm: true }, clientId()));
      if (!current()) return;
      if (opened.source.state !== "ready") throw new CommandError(422, "confirm_needed", false, undefined);
      this.referenceGrants = [...this.referenceGrants.slice(-6), { sid: id, token: opened.open_token, expiry: Date.parse(opened.expires_at) }];
      this.patch({ selections: [...this.view.selections, { source_id: id, revision: opened.source.revision }] });
    });
  }
  async startExtraction(preferCloud: boolean): Promise<void> {
    const source = this.view.source;
    if (!source) return;
    await this.action(async (current) => {
      const job = valid<W.Job>("Job", await this.mutate("POST", "/v1/study/jobs", { kind: "extract", execution: preferCloud ? "prefer_cloud" : "local", sources: [{ source_id: source.source_id, revision: source.revision }] }));
      if (current()) this.patch({ jobs: [job, ...this.view.jobs] });
    });
  }
  async loadTopics(): Promise<void> {
    const source = this.view.source;
    if (!source) return;
    await this.action(async (current) => {
      const result = valid<W.TopicLinks>("TopicLinks", await this.commands().get(`/v1/study/sources/${source.source_id}/topics`, this.headers()));
      if (current()) this.patch({ topics: result.items });
    });
  }
  async loadNotes(): Promise<void> {
    await this.action(async (current) => {
      const [sessions, saved] = await Promise.all([this.commands().get<unknown>("/v1/session-notes"), this.commands().get<unknown>("/v1/study/notes")]);
      if (!Array.isArray(sessions) || !isValid("api/commands#/$defs/StudyNoteList", saved)) throw new CommandError(200, "invalid_reply", false, undefined);
      const local = saved as { notes: { note_id: string; source: string; text: string | null; private?: boolean }[] };
      const notes: StudyWorkspaceView["notes"] = sessions.map((raw) => readSessionNote(raw)).filter((n) => n.state === "ready").map((n) => ({ id: n.note_id, kind: "session_note", title: n.private ? null : n.title, private: n.private }));
      notes.push(...local.notes.map((n) => ({ id: n.note_id, kind: (n.source === "voice" ? "dictated_note" : "board_note") as "dictated_note" | "board_note", title: n.private ? null : n.text?.slice(0, 80) ?? null, private: n.private ?? false })));
      if (current()) this.patch({ notes });
    });
  }
  async importNote(note: StudyWorkspaceView["notes"][number], confirmed: boolean): Promise<void> {
    let added: W.Source | null = null;
    await this.action(async (current) => {
      const result = valid<W.Source>("Source", await this.mutate("POST", "/v1/study/sources", { kind: note.kind, note_id: note.id, ...(confirmed ? { confirm_private: true } : {}) }));
      if (current()) added = result;
    });
    if (added) { await this.load(); await this.open((added as W.Source).source_id); }
  }
  stopReading(): void {
    this.speechGeneration++; this.cancelSpeech?.(); this.cancelSpeech = null;
    if (this.speechExpiry !== null) clearTimeout(this.speechExpiry);
    this.speechExpiry = null;
    this.finishSpeech?.(false); this.finishSpeech = null;
    if (this.view.reading) this.patch({ reading: false });
  }
  async playOverview(): Promise<void> {
    this.stopReading();
    const aid = this.view.aid, speech = this.speech;
    if (!aid || aid.kind !== "audio_overview" || aid.status !== "ready" || !speech?.available()) return;
    const generation = this.profiles.generation, reading = this.speechGeneration;
    const current = () => generation === this.profiles.generation && reading === this.speechGeneration && this.view.aid?.aid_id === aid.aid_id;
    const settings = this.profiles.getView().settings;
    const rate = settings?.speech_rate ?? 1, voice = settings?.speech_voice ?? "";
    // A two-voice podcast (STU-21) alternates the learner's voice with another voice on the device, if there is one.
    const second = aid.settings?.voices === 2 ? speech.voices?.().find((v) => v.id !== voice)?.id : undefined;
    speech.configure?.(rate, voice);
    this.patch({ reading: true, error: null });
    const expiries = aid.sources.flatMap((s) => {
      if (s.source_id === this.view.source?.source_id && this.view.source.private) return [this.grantExpires];
      return this.referenceGrants.filter((g) => g.sid === s.source_id).map((g) => g.expiry);
    });
    if (expiries.length) this.speechExpiry = setTimeout(() => this.stopReading(), Math.max(0, Math.min(...expiries) - Date.now()));
    let claim = 0, offset = 0;
    try {
      while (current()) {
        const passage = valid<W.SpeechPassage>("SpeechPassage", await this.commands().get(`/v1/study/aids/${aid.aid_id}/speech?claim=${claim}&offset=${offset}`, this.headers()));
        if (!current()) return;
        if (passage.aid_id !== aid.aid_id || passage.claim_index !== claim) throw new Error("invalid speech binding");
        this.patch({ spokenClaim: claim });
        if (second && offset === 0) speech.configure?.(rate, claim % 2 === 1 ? second : voice);
        const ok = await new Promise<boolean>((resolve) => {
          this.finishSpeech = resolve;
          this.cancelSpeech = speech.speak(passage.text, { start: () => {}, boundary: () => {}, end: () => resolve(true), error: () => resolve(false) });
        });
        this.finishSpeech = null; this.cancelSpeech = null;
        if (!current()) return;
        if (!ok) throw new Error("voice unavailable");
        if (passage.next_offset !== null) offset = passage.next_offset;
        else if (!passage.last_claim) { claim++; offset = 0; }
        else break;
      }
    } catch { if (current()) this.patch({ error: "speech_unavailable" }); }
    finally { if (current()) { if (this.speechExpiry !== null) clearTimeout(this.speechExpiry); this.speechExpiry = null; this.patch({ reading: false }); } }
  }
  /** Back from an aid to the material's study tools. */
  hideAid(): void { this.stopReading(); this.patch({ aid: null, deck: null, quiz: null, result: null }); }
  /** VOC-53, D130: a question spoken in the Chat tab was answered by a chat aid; the list gains it and it opens, as a
   * typed Chat question's answer would. Only an answer about the open source is shown. */
  async voiced(answer: { place: string; aid_id: string | null }): Promise<void> {
    const source = this.view.source;
    if (answer.place !== "study" || answer.aid_id === null || !source) return;
    try {
      const aids = await this.allAids(source.source_id);
      if (this.view.source?.source_id !== source.source_id || !aids.some((a) => a.aid_id === answer.aid_id)) return;
      this.patch({ aids });
    } catch { return; }
    await this.showAid(answer.aid_id);
  }
  async showAid(id: string): Promise<void> {
    this.stopReading();
    await this.action(async (current) => {
      const aid = valid<W.Aid>("Aid", await this.commands().get(`/v1/study/aids/${id}`, this.headers()));
      const deck = aid.deck_id ? valid<W.Deck>("Deck", await this.commands().get(`/v1/study/decks/${aid.deck_id}`, this.headers())) : null;
      const quiz = aid.quiz_id ? valid<W.QuizView>("QuizView", await this.commands().get(`/v1/study/quizzes/${aid.quiz_id}`, this.headers())) : null;
      if (current()) this.patch({ aid, deck, quiz, result: null });
    });
  }
  async rate(card: W.Flashcard, rating: "again" | "hard" | "good" | "easy"): Promise<void> {
    const deck = this.view.deck;
    if (!deck) return;
    await this.action(async (current) => {
      valid<W.ReviewResult>("ReviewResult", await this.mutate("POST", `/v1/study/decks/${deck.deck_id}/reviews`, { card_id: card.card_id, card_revision: card.revision, rating, revealed: true }));
      if (current()) this.patch({ deck: { ...deck, cards: deck.cards.filter((c) => c.card_id !== card.card_id) } });
    });
  }
  /** Back to the questions after a result, keeping the answers, for a second attempt (ASM-28). */
  clearResult(): void { if (this.view.result) this.patch({ result: null }); }
  async submit(answers: Record<string, string>): Promise<void> {
    const quiz = this.view.quiz;
    if (!quiz) return;
    await this.action(async (current) => {
      const result = valid<W.QuizResult>("QuizResult", await this.mutate("POST", `/v1/study/quizzes/${quiz.quiz_id}/attempts`, { quiz_revision: quiz.revision, answers: Object.entries(answers).filter(([, a]) => a.trim()).map(([item_id, answer]) => ({ item_id, answer })) }));
      if (current()) { const { draft: _, ...rest } = quiz; this.patch({ result, quiz: rest }); }
    });
    await this.load();
  }
  async correctText(text: string): Promise<void> {
    const source = this.view.source;
    if (!source) return;
    let saved = false;
    await this.action(async (current) => {
      valid<W.Source>("Source", await this.mutate("POST", `/v1/study/sources/${source.source_id}/revisions`, { expected_revision: source.revision, text }));
      saved = current();
    });
    if (saved) await this.open(source.source_id);
  }
  async markPrivate(): Promise<void> {
    const source = this.view.source;
    if (!source) return;
    await this.action(async (current) => {
      valid<W.Source>("Source", await this.mutate("PATCH", `/v1/study/sources/${source.source_id}`, { private: !source.private }));
      if (current()) this.close();
    });
    await this.load();
  }
  async remove(): Promise<void> {
    const source = this.view.source;
    if (!source) return;
    await this.action(async (current) => {
      const receipt = valid<W.DeleteReceipt>("DeleteReceipt", await this.mutate("DELETE", `/v1/study/sources/${source.source_id}`));
      if (current()) { this.close(); this.patch({ cleanupPending: receipt.cloud_cleanup === "pending" }); }
    });
    await this.load();
  }
  async loadPage(page: number, revision?: number, sourceId?: string): Promise<Blob | null> {
    const source = this.view.source;
    if (!source) return null;
    let result: Blob | null = null;
    await this.action(async (current) => {
      const blob = await this.commands().request<Blob>("GET", `/v1/study/sources/${sourceId ?? source.source_id}/pages/${page}?revision=${revision ?? source.revision}`, undefined, null, this.headers(), true);
      if (blob.type !== "image/png" || blob.size > 2500000) throw new CommandError(200, "invalid_reply", false, undefined);
      if (current()) result = blob;
    });
    return result;
  }
  async readCitation(citation: W.Citation): Promise<boolean> {
    let ok = false;
    await this.action(async (current) => {
      if (citation.source_id !== this.view.source?.source_id || citation.revision !== this.view.source.revision) {
        const opened = valid<W.OpenedSource>("OpenedSource", await this.commands().post(`/v1/study/sources/${citation.source_id}/open`, { confirm: true, revision: citation.revision }, clientId()));
        if (!current()) return;
        this.referenceGrants = [...this.referenceGrants.slice(-6), { sid: citation.source_id, token: opened.open_token, expiry: Date.parse(opened.expires_at) }];
      }
      const chunks: W.Chunk[] = [];
      let cursor: string | null = null;
      do {
        const reply: W.ChunkList = valid("ChunkList", await this.commands().get(`/v1/study/sources/${citation.source_id}/content?revision=${citation.revision}&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, this.headers()));
        if (!current()) return;
        chunks.push(...reply.items); cursor = reply.next_cursor;
      } while (cursor !== null);
      const cited = chunks.find((c) => c.chunk_id === citation.chunk_id && Array.from(c.text).slice(citation.start, citation.end).join("") === citation.quote);
      if (!cited) throw new CommandError(200, "invalid_reply", false, undefined);
      if (current()) {
        this.patch({ chunks }); ok = true;
        // A citation to a recording opens the player at that moment (STU-22).
        if (cited.locator.kind === "time" && citation.source_id === this.view.source?.source_id) this.seek(cited.locator.start_ms);
      }
    });
    return ok;
  }
  async refreshOpened(): Promise<void> {
    await this.load();
    const source = this.view.source;
    if (!source || this.view.busy) return;
    const generation = this.profiles.generation, selection = this.selection;
    try {
      const raw = await this.commands().get(`/v1/study/sources/${source.source_id}`);
      const summary = valid<W.SourceList>("SourceList", { items: [raw], next_cursor: null }).items[0];
      if (!summary) throw new CommandError(200, "invalid_reply", false, undefined);
      const fresh = this.view.followCurrent && "title" in summary ? summary : source;
      const chunks: W.Chunk[] = [];
      if (this.view.chunks.length === 0 || fresh.revision !== source.revision) {
        let cursor: string | null = null;
        do {
          const result: W.ChunkList = valid("ChunkList", await this.commands().get(`/v1/study/sources/${source.source_id}/content?revision=${fresh.revision}&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, this.headers()));
          if (generation !== this.profiles.generation || selection !== this.selection) return;
          chunks.push(...result.items); cursor = result.next_cursor;
        } while (cursor !== null);
      }
      const aids = await this.allAids(source.source_id);
      if (generation === this.profiles.generation && selection === this.selection) {
        // The question just asked in the Chat tab: its answer replaces the one on screen once it is ready (STU-20).
        const asked = this.askedChat !== null ? aids.find((a) => a.job_id === this.askedChat && a.status === "ready") : undefined;
        if (asked) this.askedChat = null;
        const aid = asked ?? (this.view.aid ? aids.find((a) => a.aid_id === this.view.aid?.aid_id) ?? null : null);
        if (!aid || aid.status === "stale" || fresh.revision !== source.revision) this.stopReading();
        if (fresh.revision !== source.revision) this.patch({ topics: [] });
        if (!aid) this.patch({ deck: null, quiz: null, result: null });
        this.patch({ source: fresh, chunks: this.view.chunks.length === 0 || fresh.revision !== source.revision ? chunks : this.view.chunks, aids, aid,
          quiz: this.view.quiz && aid?.status === "stale" ? { ...this.view.quiz, status: "stale" } : this.view.quiz });
      }
    } catch (error) {
      if (generation === this.profiles.generation && selection === this.selection) {
        if (error instanceof CommandError && error.details?.reason === "grant_expired") this.close();
        if (error instanceof CommandError && error.code === "not_found") { this.close(); return; }
        this.patch({ error: error instanceof CommandError ? String(error.details?.reason ?? error.code) : "unreachable" });
      }
    }
  }
}
