// No browser storage: the working copy is the sole durable draft store (AUT-03).
import { StudioError, type Command, type Data, type Opened, type Report } from "./model.js";
export interface DraftView { text: string; dirty: boolean; saving: boolean; conflict: boolean; error: string | null; report: Report | null }
export class Draft {
  private state: DraftView;
  private listeners = new Set<() => void>();
  private revision: string;
  private generation = 0;
  private identity: Data["id"] | undefined;
  private fresh: boolean;
  private running: Promise<boolean> | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private checkTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;
  constructor(readonly opened: Opened, private command: Command, private author: string | null) {
    this.revision = opened.revision;
    this.identity = opened.record.id; this.fresh = opened.new === true;
    this.state = { text: JSON.stringify(opened.record, null, 2), dirty: opened.new ?? false, saving: false, conflict: false, error: null, report: null };
    this.check();
    if (opened.new) this.saveTimer = setTimeout(() => { void this.flush(); }, 5000);
  }
  getState = (): DraftView => this.state;
  canEditIdentity = (): boolean => this.fresh && !this.state.saving;
  getRevision = (): string => this.revision;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private update(change: Partial<DraftView>): void { if (this.closed) return; this.state = { ...this.state, ...change }; for (const fn of this.listeners) fn(); }
  change(text: string): void {
    ++this.generation; this.update({ text, dirty: true, error: null, report: null });
    if (this.saveTimer) clearTimeout(this.saveTimer);
    if (this.checkTimer) clearTimeout(this.checkTimer);
    this.saveTimer = setTimeout(() => { void this.flush(); }, 5000);
    this.checkTimer = setTimeout(() => this.check(), 400);
  }
  private parsed(): Data {
    const record: unknown = JSON.parse(this.state.text);
    if (record === null || typeof record !== "object" || Array.isArray(record)) throw new Error("The record must be a JSON object.");
    return record as Data;
  }
  check(): void {
    const generation = this.generation;
    try {
      const record = this.parsed();
      void this.command<Report>({ op: "validate", pack: this.opened.pack, table: this.opened.table, record }).then((report) => {
        if (generation === this.generation) this.update({ report });
      }).catch((error: unknown) => { if (generation === this.generation) this.update({ error: String(error) }); });
    } catch { this.update({ error: "Finish the JSON object before it can be saved or checked." }); }
  }
  async flush(): Promise<boolean> {
    if (this.closed) return false;
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = null;
    if (this.running) { if (!await this.running) return false; return this.flush(); }
    if (!this.state.dirty) return true;
    if (this.state.conflict || this.author === null) {
      this.update({ error: this.state.conflict ? "Copy your draft or reload the changed file before saving." : "Select an authoring account to save." }); return false;
    }
    let record: Data;
    try { record = this.parsed(); } catch { this.update({ error: "Finish the JSON object before saving." }); return false; }
    const generation = this.generation;
    this.update({ saving: true, error: null });
    this.running = this.command<Opened>({ op: "save", pack: this.opened.pack, table: this.opened.table,
      id: this.fresh ? record.id : this.identity, record, revision: this.revision, author: this.author }).then((saved) => {
      this.revision = saved.revision;
      this.identity = saved.record.id; this.fresh = false;
      if (generation === this.generation) this.update({ text: JSON.stringify(saved.record, null, 2), dirty: false });
      else {
        const newer = this.parsed();
        for (const key of ["version", "review", "authoring"]) if (saved.record[key] !== undefined) newer[key] = saved.record[key];
        this.update({ text: JSON.stringify(newer, null, 2) });
      }
      return true;
    }).catch((error: unknown) => {
      this.update({ error: error instanceof Error ? error.message : String(error), conflict: error instanceof StudioError && error.code === "conflict" }); return false;
    }).finally(() => { this.running = null; this.update({ saving: false }); });
    // Navigation and native close may proceed only after edits made during this save are durable too.
    const saved = await this.running;
    return saved ? this.flush() : false;
  }
  close(): void { this.closed = true; if (this.saveTimer) clearTimeout(this.saveTimer); if (this.checkTimer) clearTimeout(this.checkTimer); this.listeners.clear(); }
}
