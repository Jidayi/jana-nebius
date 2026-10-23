import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ContractForm } from "./Form.js";
import { Draft } from "./draft.js";
import { command } from "./transport.js";
import { object, type Command, type Data, type Json, type Opened, type Report, type Schema } from "./model.js";
interface Reference { rows: Json[]; revision: string; path: string; schema: Schema; report: Report }
const opened = (pack: string, value: Reference): Opened => ({ pack, table: "conventions", path: value.path, revision: value.revision, record: { id: "conventions", rows: value.rows } });
const transport: Command = async <T,>(request: Record<string, unknown>) => {
  const value = await command<Reference>({ op: request.op === "validate" ? "reference_check" : "reference_save", pack: request.pack, table: "conventions", rows: (request.record as Data).rows, revision: request.revision, author: request.author });
  return (request.op === "validate" ? value.report : opened(String(request.pack), value)) as T;
};
const empty = () => () => undefined, blank = { text: "{}", dirty: false, saving: false, conflict: false, error: null, report: null }, readBlank = () => blank;
export function ReferenceEditor({ pack, author, registerGuard, onClose }: { pack: string; author: string | null; registerGuard(guard: () => Promise<boolean>): void; onClose(): void }) {
  const dialog = useRef<HTMLDialogElement>(null), [draft, setDraft] = useState<Draft | null>(null), [schema, setSchema] = useState<Schema | null>(null), [error, setError] = useState("");
  const state = useSyncExternalStore(draft?.subscribe ?? empty, draft?.getState ?? readBlank), record = object(JSON.parse(state.text) as Json);
  useEffect(() => { dialog.current?.showModal(); let alive = true; void command<Reference>({ op: "reference_open", pack, table: "conventions" }).then((value) => { if (alive) { setSchema(value.schema); setDraft(new Draft(opened(pack, value), transport, author)); } }).catch((e: unknown) => { if (alive) setError(String(e)); }); return () => { alive = false; }; }, [pack, author]);
  useEffect(() => { registerGuard(async () => draft === null || await draft.flush()); return () => registerGuard(async () => true); }, [draft]);
  useEffect(() => () => draft?.close(), [draft]);
  useEffect(() => { const before = (e: BeforeUnloadEvent) => { if (draft?.getState().dirty) e.preventDefault(); }; window.addEventListener("beforeunload", before); return () => window.removeEventListener("beforeunload", before); }, [draft]);
  const close = async () => { if (draft === null || await draft.flush()) onClose(); };
  return <dialog ref={dialog} aria-label="Conventions" onCancel={(e) => { e.preventDefault(); void close(); }}><header><h2>Conventions</h2><button type="button" onClick={() => void close()}>Close</button></header>
    {draft && schema && <><ContractForm schema={{ type: "array", items: { $ref: "#/$defs/Convention" } }} root={schema} value={record.rows} records={[]} path="$.conventions" onChange={(rows) => draft.change(JSON.stringify({ ...record, rows }))} /><button type="button" disabled={!state.dirty || state.saving || !author} onClick={() => void draft.flush()}>Save conventions</button><ul>{state.report?.problems.map((p, i) => <li key={i}>{p}</li>)}</ul></>}
    {(error || state.error) && <p role="alert">{error || state.error}</p>}
  </dialog>;
}
