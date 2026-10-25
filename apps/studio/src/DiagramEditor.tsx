import { createElement, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { type VisualSpec } from "@jana/ui";
import { RENDERERS, parseSvg, svgProblems, reactProps, type SvgNode } from "@jana/renderers";
import { Workflow } from "./Workflow.js";
import { ContractForm } from "./Form.js";
import { Draft } from "./draft.js";
import { command } from "./transport.js";
import { object, type Command, type Data, type Json, type Opened, type Report, type Schema } from "./model.js";
import { hooksOf, StudioVisual } from "./visuals.js";
interface DiagramOpened { entry: Data; svg: string; revision: string; svg_revision: string; report: Report }
const opened = (pack: string, value: DiagramOpened): Opened => ({ pack, table: "diagrams", path: String(value.entry.id), revision: value.revision, record: { id: value.entry.id ?? null, entry: value.entry, svg: value.svg } });
function transportFor(pack: string, initialSvgRevision: string): Command {
  let svgRevision = initialSvgRevision;
  return async <T,>(request: Record<string, unknown>): Promise<T> => {
    const record = request.record as Data;
    if (request.op === "validate") return await command({ op: "diagram_check", pack, entry: record.entry, svg: record.svg });
    const saved = await command<DiagramOpened>({ op: "diagram_save", pack, id: record.id, entry: record.entry, svg: record.svg, revision: request.revision, svg_revision: svgRevision, author: request.author });
    svgRevision = saved.svg_revision; return opened(pack, saved) as T;
  };
}
const empty = () => () => undefined, blank = { text: "{}", dirty: false, saving: false, conflict: false, error: null, report: null }, readBlank = () => blank;
const library = RENDERERS.find((r) => r.kind === "library_diagram");
export function DiagramEditor({ pack, diagrams, author, registerGuard, onClose }: {
  pack: string; diagrams: { id: string; title: string }[]; author: string | null;
  registerGuard(guard: () => Promise<boolean>): void; onClose(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null), [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [schema, setSchema] = useState<Schema | null>(null);
  const [element, setElement] = useState(0), [part, setPart] = useState(""), [newId, setNewId] = useState("");
  const [extra, setExtra] = useState<{ id: string; title: string }[]>([]);
  const state = useSyncExternalStore(draft?.subscribe ?? empty, draft?.getState ?? readBlank);
  const record = object(JSON.parse(state.text) as Json), entry = object(record.entry), svg = String(record.svg ?? "");
  const report = state.report as (Report & { schema?: Schema }) | null;
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => { if (report?.schema) setSchema(report.schema); }, [report]);
  useEffect(() => { registerGuard(async () => draft === null || await draft.flush()); return () => registerGuard(async () => true); }, [draft]);
  useEffect(() => () => draft?.close(), [draft]);
  useEffect(() => { const before = (e: BeforeUnloadEvent) => { if (draft?.getState().dirty) e.preventDefault(); }; window.addEventListener("beforeunload", before); return () => window.removeEventListener("beforeunload", before); }, [draft]);
  const install = (value: DiagramOpened) => { setDraft(new Draft(opened(pack, value), transportFor(pack, value.svg_revision), author)); setSchema(null); setNotice(""); setError(""); };
  const open = async (id: string) => { try { if (!id || draft && !await draft.flush()) return; install(await command<DiagramOpened>({ op: "diagram_open", pack, id })); } catch (e) { setError(String(e)); } };
  const change = (fields: Data) => {
    if (!draft) return;
    const current = object(JSON.parse(draft.getState().text) as Json);
    draft.change(JSON.stringify({ ...current, ...fields }));
  };
  const close = async () => { if (!draft || await draft.flush()) onClose(); };
  const editSvg = async (op: string) => { try {
    if (!draft) return;
    const submitted = String(object(JSON.parse(draft.getState().text) as Json).svg ?? "");
    const result = await command<{ svg: string; removed?: string[] }>({ op, pack, svg: submitted, element, part });
    const current = object(JSON.parse(draft.getState().text) as Json);
    if (current.svg !== submitted) { setError("The drawing changed during this action; run it again."); return; }
    draft.change(JSON.stringify({ ...current, svg: result.svg })); setNotice(result.removed ? `Removed: ${result.removed.join(", ") || "nothing unsafe"}` : "Part tag updated");
  } catch (e) { setError(String(e)); } };
  const duplicate = async () => { try { const saved = await command<DiagramOpened>({ op: "diagram_duplicate", pack, id: record.id, new_id: newId, entry, svg, author });
    setExtra([...extra, { id: String(saved.entry.id), title: String(saved.entry.title) }]); install(saved);
  } catch (e) { setError(String(e)); } };
  let root: SvgNode | null = null;
  try { const parsed = parseSvg(svg); if (svgProblems(parsed).length === 0) root = parsed; } catch { /* Unsafe source stays editable and is never injected. */ }
  const nodes: { index: number; tag: string; label: string }[] = [];
  let index = 0;
  const draw = (node: SvgNode): ReactNode => {
    const n = index++, label = node.children.filter((c): c is string => typeof c === "string").join(" ");
    nodes.push({ index: n, tag: node.tag, label });
    return createElement(node.tag, { ...reactProps(node.attrs), key: n, onClick: (e: { stopPropagation(): void }) => { e.stopPropagation(); setElement(n); } }, ...node.children.map((c) => typeof c === "string" ? c : draw(c)));
  };
  const canvas = root ? draw(root) : null;
  return <dialog ref={dialog} className="skill-dialog" aria-label="Diagram manager" onCancel={(e) => { e.preventDefault(); void close(); }}>
    <div className="row"><h1>Diagram manager</h1><button type="button" onClick={() => void close()}>Close diagram manager</button></div>
    <label className="field">Diagram<select aria-label="Diagram" value={String(record.id ?? "")} onChange={(e) => void open(e.target.value)}><option value="">Choose a diagram</option>{[...diagrams, ...extra].map((d) => <option key={d.id} value={d.id}>{d.title} · {d.id}</option>)}</select></label>
    {draft && <><button type="button" disabled={!author || state.saving || state.conflict} onClick={() => void draft.flush()}>Save diagram draft</button><p role="status">{state.conflict ? "Conflict · draft retained" : state.dirty ? "Unsaved drawing changes" : "Saved on this computer"}</p>
      {schema && <ContractForm root={schema} schema={schema} value={entry} records={[]} onChange={(next) => change({ entry: next })} />}
      <label className="field">SVG source<textarea rows={12} value={svg} onChange={(e) => change({ svg: e.target.value })} /></label>
      <button type="button" onClick={() => void editSvg("diagram_sanitise")}>Sanitise drawing and show removals</button>
      <div aria-hidden="true" className="diagram-tag-canvas">{canvas}</div>
      <label className="field">Drawing element<select value={element} onChange={(e) => setElement(Number(e.target.value))}>{nodes.map((n) => <option key={n.index} value={n.index}>{n.index} · {n.tag} {n.label}</option>)}</select></label>
      <label className="field">Assign part<select value={part} onChange={(e) => setPart(e.target.value)}><option value="">Choose a declared part</option>{(Array.isArray(entry.parts) ? entry.parts : []).map(object).map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.name)} · {String(p.id)}</option>)}</select></label>
      <button type="button" disabled={!part || !canvas} onClick={() => void editSvg("diagram_tag")}>Tag selected element</button>
      <section aria-label="Diagram licence register"><p>Licence: {String(entry.licence)} · Attribution: {String(entry.attribution ?? "")}</p><p>Reverified: {String(object(entry.review).approved_at ?? "Not recorded")}</p></section>
      <h2>Production preview</h2>{report?.preview && library && <StudioVisual spec={report.preview as unknown as VisualSpec} hooks={hooksOf(library)} />}
      <ul>{report?.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
      <details><summary>Create a new diagram identity</summary><label className="field">New diagram id<input value={newId} onChange={(e) => setNewId(e.target.value)} /></label><button type="button" disabled={!author || !newId} onClick={() => void duplicate()}>Copy edits to new diagram</button></details>
      <Workflow pack={pack} table="diagrams" record={entry} author={author} beforeSave={() => draft.flush()} readRecord={() => object(object(JSON.parse(draft.getState().text)).entry)} preview={(value) => library ? <StudioVisual spec={value as unknown as VisualSpec} hooks={hooksOf(library)} /> : null} />
      {state.error && <p role="alert">{state.error}</p>}
      {state.conflict && <button type="button" onClick={() => { const a = document.createElement("a"), url = URL.createObjectURL(new Blob([state.text], { type: "application/json" })); a.href = url; a.download = `${String(record.id)}.draft.json`; a.click(); URL.revokeObjectURL(url); }}>Download retained diagram draft</button>}
    </>}{notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </dialog>;
}
