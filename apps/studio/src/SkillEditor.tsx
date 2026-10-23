import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Workflow } from "./Workflow.js";
import { ContractForm } from "./Form.js";
import { Draft } from "./draft.js";
import { command } from "./transport.js";
import { object, type Command, type Data, type Json, type Opened, type Report, type Schema } from "./model.js";

interface SkillOpened { name: string; text: string; revision: string; report: Data }
const opened = (value: SkillOpened): Opened => ({ pack: "workspace", table: "skills", path: value.name, revision: value.revision, record: { id: value.name, text: value.text } });
const report = (value: Data): Report => ({ ...value, ok: value.ok === true, problems: (Array.isArray(value.findings) ? value.findings : []).map((f) => { const row = object(f); return `${String(row.rule)} · line ${String(row.line)}: ${String(row.message)}`; }) });
export const skillTransport: Command = async <T,>(request: Record<string, unknown>): Promise<T> => {
  const record = request.record as Data;
  if (request.op === "validate") return report(await command<Data>({ op: "skill_check", name: record.id, text: record.text })) as T;
  if (request.op === "save") return opened(await command<SkillOpened>({ op: "skill_save", name: record.id, text: record.text, revision: request.revision, author: request.author })) as T;
  throw new Error("Unsupported skill draft operation");
};
const empty = () => () => undefined;
const blank = { text: "{}", dirty: false, saving: false, conflict: false, error: null, report: null };
const readBlank = () => blank;
export function SkillEditor({ skills, author, registerGuard, onClose, pack = "" }: {
  pack?: string; skills: { name: string; kind: string; path: string }[]; author: string | null;
  registerGuard(guard: () => Promise<boolean>): void; onClose(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null), composing = useRef<Promise<void>>(Promise.resolve()), generation = useRef(0), composeFailed = useRef(false);
  const [draft, setDraft] = useState<Draft | null>(null), [error, setError] = useState(""), [formReport, setFormReport] = useState<Data | null>(null);
  const state = useSyncExternalStore(draft?.subscribe ?? empty, draft?.getState ?? readBlank);
  const record = object(JSON.parse(state.text) as Json), source = String(record.text ?? ""), details = formReport;
  useEffect(() => { if (state.report) setFormReport(state.report as unknown as Data); }, [state.report]);
  const flush = async () => { await composing.current; return !composeFailed.current && (draft === null || await draft.flush()); };
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => { registerGuard(flush); return () => registerGuard(async () => true); }, [draft]);
  useEffect(() => () => draft?.close(), [draft]);
  useEffect(() => { const before = (e: BeforeUnloadEvent) => { if (draft?.getState().dirty) e.preventDefault(); }; window.addEventListener("beforeunload", before); return () => window.removeEventListener("beforeunload", before); }, [draft]);
  const open = async (name: string) => { try { if (!name || !await flush()) return; setDraft(new Draft(opened(await command<SkillOpened>({ op: "skill_open", name })), skillTransport, author)); setError(""); } catch (e) { setError(String(e)); } };
  const change = (text: string) => draft?.change(JSON.stringify({ id: record.id, text }));
  const compose = (meta: Json, body: string) => {
    const id = ++generation.current; composeFailed.current = false; setFormReport({ ...details, frontmatter: meta, body });
    composing.current = command<{ text: string }>({ op: "skill_compose", name: record.id, frontmatter: meta, body }).then((next) => { if (generation.current === id) change(next.text); }).catch((e: unknown) => { if (generation.current === id) { composeFailed.current = true; setError(String(e)); } });
  };
  const close = async () => { if (await flush()) onClose(); };
  const submit = async () => { try { if (!draft || !await flush()) return; const result = await command<Data>({ op: "skill_submit", name: record.id, text: source, author, revision: draft.getRevision() });
    if (result.ok) await open(String(record.id)); else setError(Array.isArray(result.problems) ? result.problems.map(String).join("\n") : "Submission failed"); } catch (e) { setError(String(e)); } };
  return <dialog ref={dialog} className="skill-dialog" aria-label="Skill editor" onCancel={(e) => { e.preventDefault(); void close(); }}>
    <div className="row"><h1>Skill editor</h1><button type="button" onClick={() => void close()}>Close skill editor</button></div>
    <label className="field">Skill<select aria-label="Skill" value={String(record.id ?? "")} onChange={(e) => void open(e.target.value)}><option value="">Choose a skill</option>{skills.map((s) => <option key={s.path} value={s.name}>{s.kind} · {s.name}</option>)}</select></label>
    {draft && <><div className="row"><button type="button" disabled={!author || state.saving || state.conflict} onClick={() => void flush()}>Save skill draft</button>
      <button type="button" disabled={!author || state.saving || state.conflict} onClick={() => void submit()}>Submit skill through gates</button><span role="status">{state.conflict ? "Conflict · draft retained" : state.dirty ? "Unsaved skill changes" : "Saved on this computer"}</span></div>
      {details?.schema && <details><summary>Front-matter form and body</summary><ContractForm readOnlyFields={["name"]} root={details.schema as unknown as Schema} schema={details.schema as unknown as Schema} value={details.frontmatter} records={[]} onChange={(next) => compose(next, String(details.body ?? ""))} />
        <label className="field">Skill body<textarea rows={20} value={String(details.body ?? "")} onChange={(e) => compose(details.frontmatter ?? {}, e.target.value)} /></label>
        <button type="button" onClick={() => compose(details.frontmatter ?? {}, `${String(details.body ?? "")}\n${(Array.isArray(details.sections) ? details.sections : []).filter((s) => !String(details.body).includes(`## ${String(s)}`)).map((s) => `## ${String(s)}\n\n`).join("\n")}`)}>Add missing section skeleton</button></details>}
      <label className="field">Complete skill source<textarea className="json-source" rows={20} value={source} onChange={(e) => { ++generation.current; composeFailed.current = false; setFormReport(null); change(e.target.value); }} /></label>
      <section aria-label="Skill lint findings"><h2>Lint and injection scan</h2><ul>{state.report?.problems.map((p, i) => <li key={i}>{p}</li>)}</ul></section>
      {details && <><p>Eval cases: {String(details.eval_cases ?? 0)} / {String(details.eval_minimum ?? 0)} minimum · {details.current_evals_green ? "Current evals green" : "Current local-model evaluation required"}</p>
        <details><summary>Role index budget</summary><pre>{JSON.stringify(details.index_budget, null, 2)}</pre></details><details><summary>Role slice previews</summary><pre>{JSON.stringify(details.role_slices, null, 2)}</pre></details></>}
      <Workflow pack={pack} table="skills" record={record} author={author} beforeSave={flush} readRecord={() => object(JSON.parse(draft.getState().text))} preview={() => null} />
      {state.error && <p role="alert">{state.error}</p>}
      {state.conflict && <button type="button" onClick={() => { const a = document.createElement("a"), url = URL.createObjectURL(new Blob([source], { type: "text/markdown" })); a.href = url; a.download = `${String(record.id)}.draft.md`; a.click(); URL.revokeObjectURL(url); }}>Download retained skill draft</button>}
    </>}{error && <p role="alert">{error}</p>}
  </dialog>;
}
