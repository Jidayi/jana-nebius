import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { BrandMark, ConfirmDialog, ErrorState, ExampleBoard, LessonPlayerContent, LocaleProvider, RegistryProvider, defaultRegistry } from "@jana/ui";
import { RENDERERS } from "@jana/renderers";
import type { LessonView, WorkedExampleView } from "@jana/client-core";
import { ContractForm, recordSchema } from "./Form.js";
import { Draft } from "./draft.js";
import { command, exitStudio, openWorkspace } from "./transport.js";
import { object, type Data, type Opened, type Report, type Summary, type Workspace } from "./model.js";
import { KCGraph } from "./KCGraph.js";
import { registerVisuals } from "./visuals.js";
import { Experiments } from "./Experiments.js";
import { Workflow } from "./Workflow.js";
import { Changes } from "./Changes.js";
import { SkillEditor } from "./SkillEditor.js";
import { DiagramEditor } from "./DiagramEditor.js";
import { ExampleTools } from "./ExampleTools.js";
import { ReferenceEditor } from "./ReferenceEditor.js";
import { BulkImport } from "./BulkImport.js";

const registry = registerVisuals(defaultRegistry(), RENDERERS);
const names: Record<string, string> = { curriculum_nodes: "Curriculum", kcs: "Knowledge components", lessons: "Lessons", items: "Items", worked_examples: "Worked examples", misconceptions: "Misconceptions", item_templates: "Templates", visual_presets: "Visual presets", mock_papers: "Mock papers", charts_of_accounts: "Chart of accounts" };
const title = (record: Data) => String(record.title ?? record.statement ?? record.stem ?? record.id);
const empty = () => () => undefined;
const blank = { text: "", dirty: false, saving: false, conflict: false, error: null, report: null };
const readBlank = () => blank;

export function App() {
  const [referenceOpen, setReferenceOpen] = useState(false);
  const [workspace, setWorkspace] = useState<Workspace | null>(null), [pack, setPack] = useState("");
  const [table, setTable] = useState("curriculum_nodes"), [query, setQuery] = useState(""), [topic, setTopic] = useState("");
  const [author, setAuthor] = useState<string | null>(null), [draft, setDraft] = useState<Draft | null>(null);
  const [mode, setMode] = useState<"form" | "json">("form"), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [confirmReload, setConfirmReload] = useState(false);
  const [diagramOpen, setDiagramOpen] = useState(false), [importOpen, setImportOpen] = useState(false);
  const [skillOpen, setSkillOpen] = useState(false), toolGuard = useRef<() => Promise<boolean>>(async () => true);
  const [packReport, setPackReport] = useState<Report | null>(null), [refs, setRefs] = useState<{ records: { id: string; table: string }[]; skills: string[] } | null>(null);
  const state = useSyncExternalStore(draft?.subscribe ?? empty, draft?.getState ?? readBlank);
  const currentPack = workspace?.packs.find((p) => p.id === pack);
  const allRecords = workspace?.packs.flatMap((p) => p.records) ?? [];
  const record = useMemo<Data | null>(() => {
    try { return object(JSON.parse(state.text)); } catch { return null; }
  }, [state.text]);
  const modalGuard = useRef<() => Promise<boolean>>(async () => true);
  const readyToLeave = async () => (draft === null || await draft.flush()) && await toolGuard.current() && await modalGuard.current();
  useEffect(() => () => draft?.close(), [draft]);
  useEffect(() => {
    const before = (event: BeforeUnloadEvent) => { if (draft?.getState().dirty) event.preventDefault(); };
    const hide = () => { void draft?.flush(); };
    const close = () => { void readyToLeave().then((ok) => { if (ok) void exitStudio(); }); };
    window.addEventListener("beforeunload", before); window.addEventListener("pagehide", hide);
    window.addEventListener("studio-close-request", close);
    return () => { window.removeEventListener("beforeunload", before); window.removeEventListener("pagehide", hide); window.removeEventListener("studio-close-request", close); };
  }, [draft]);
  const install = (opened: Opened) => { setDraft(new Draft(opened, command, author)); setMode("form"); setPackReport(null); setMessage(""); };
  const open = async (item: Summary) => {
    if (!await readyToLeave()) return;
    setBusy(true);
    try {
      const owner = workspace?.packs.find((candidate) => candidate.records.some((row) => row.id === item.id))?.id ?? pack;
      const opened = await command<Opened>({ op: "open", pack: owner, table: item.table, id: item.id });
      setPack(owner); setTable(item.table);
      install(opened);
      setRefs(await command({ op: "references", pack: opened.pack, id: item.id }));
    } catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const openRoot = async () => {
    if (!await readyToLeave()) return;
    setBusy(true);
    try {
      const next = await openWorkspace(); if (!next) return;
      setWorkspace(next); setTable(next.tables[0] ?? "curriculum_nodes"); setPack(next.packs[0]?.id ?? ""); setAuthor(next.author ?? next.accounts[0]?.id ?? null);
      setDraft(null); setTopic(""); setMessage("");
    } catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const checkPack = async (category: string) => {
    if (!await readyToLeave()) return;
    setBusy(true); setMessage(`Running aut ${category}…`);
    try { setPackReport(await command({ op: "check", category, pack })); setMessage(`aut ${category} finished.`); }
    catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const duplicate = async (name: string) => {
    if (!draft || !await readyToLeave()) return;
    try { install(await command({ op: "duplicate", pack, table: draft.opened.table, id: draft.opened.record.id, title: name })); setRefs(null); }
    catch (error) { setMessage(String(error)); }
  };
  const reloadDisk = async () => {
    if (!draft) return;
    setConfirmReload(false); setBusy(true);
    try {
      // Retain the current editor until the replacement is available, even if the disk read fails.
      install(await command<Opened>({ op: "open", pack: draft.opened.pack,
        table: draft.opened.table, id: draft.opened.record.id }));
    } catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const topics = currentPack?.records.filter((r) => r.table === "curriculum_nodes") ?? [];
  const visible = (currentPack?.records ?? []).filter((r) => r.table === table && (!topic || r.id.startsWith(topic) || r.node_id?.startsWith(topic)) &&
    `${r.id} ${r.code ?? ""} ${r.title}`.toLowerCase().includes(query.toLowerCase()));
  const depth = (item: Summary): number => { let n = 0, parent = item.node_id; const seen = new Set<string>(); while (parent && !seen.has(parent)) { seen.add(parent); ++n; parent = topics.find((r) => r.id === parent)?.node_id ?? null; } return n; };
  return <LocaleProvider locale="en"><RegistryProvider registry={registry}><div className="studio">
    <header className="topbar"><div className="brand"><BrandMark kind="lockup" height={24} /><span className="studio-word">Studio</span></div>
      <span className="offline">● Offline authoring</span><button type="button" disabled={busy} onClick={() => void openRoot()}>{workspace ? "Open another workspace" : "Open workspace"}</button></header>
    {!workspace ? <main className="welcome"><p className="eyebrow">CONTENT WORKSPACE</p><h1>Good teaching starts here.</h1><p>Open a local content repository to edit curriculum, verify answers and preview lessons. Your drafts stay in the working copy.</p>
      <button type="button" className="primary" disabled={busy} onClick={() => void openRoot()}>{busy ? "Opening content…" : "Open local workspace"}</button>
      <p className="text-meta">In the browser preview, this opens the repository configured by the local development server.</p>{message && <ErrorState message={message} />}</main> : <>
      <div className="workspace-bar"><label>Pack<select aria-label="Pack" value={pack} disabled={busy} onChange={(e) => { const next = e.target.value; void readyToLeave().then((ok) => { if (ok) { setPack(next); setDraft(null); setTopic(""); } }); }}>{workspace.packs.map((p) => <option key={p.id} value={p.id}>{p.subject.toUpperCase()} · {p.level.toUpperCase()}</option>)}</select></label>
        <span className="workspace-path" title={workspace.root}>{workspace.root}</span>
        <label>Author<select aria-label="Author" disabled={busy} value={author ?? ""} onChange={(e) => { const next = e.target.value; void readyToLeave().then((ok) => { if (ok) { setAuthor(next || null); setDraft(null); } }); }}><option value="">Read only</option>{workspace.accounts.map((a) => <option key={a.id} value={a.id}>{a.name || a.id}</option>)}</select></label></div>
      {workspace.accounts.length === 0 && <Bootstrap onCreated={async () => { const next = await command<Workspace>({ op: "workspace" }); setWorkspace(next); setAuthor(next.accounts[0]?.id ?? null); }} />}
      <div className="body-grid"><aside className="sidebar"><h2>Content library</h2><nav aria-label="Content types">{workspace.tables.map((key) => <button type="button" key={key} aria-current={table === key ? "page" : undefined} onClick={() => { setTable(key); setTopic(""); }}>{names[key] ?? key}<span>{currentPack?.records.filter((r) => r.table === key).length}</span></button>)}</nav>
        <label className="field">Find a record<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Title, code or id" /></label>
        <label className="field">Topic<select value={topic} onChange={(e) => setTopic(e.target.value)}><option value="">All topics</option>{topics.map((r) => <option key={r.id} value={r.id}>{r.code} · {r.title}</option>)}</select></label>
        <div className="record-list" aria-label="Records">{visible.map((item) => <button type="button" key={item.id} disabled={busy} aria-current={draft?.opened.record.id === item.id ? "true" : undefined} style={table === "curriculum_nodes" ? { paddingInlineStart: `${12 + depth(item) * 10}px` } : undefined} onClick={() => void open(item)}><small>{item.code ?? item.id.split(".").slice(-2).join(".")}</small><span>{item.title}</span></button>)}{visible.length === 0 && <p>No matching records.</p>}</div>
      </aside><main className="editor-area">
        <div className="pipeline"><span>CLI pipeline</span><button type="button" disabled={busy} onClick={() => { void readyToLeave().then((ok) => { if (ok) setReferenceOpen(true); }); }}>Edit conventions</button>{["validate", "verify", "lint", "qa", "scan"].map((category) => <button type="button" key={category} disabled={busy} onClick={() => void checkPack(category)}>{category}</button>)}<button type="button" disabled={busy} onClick={() => { void readyToLeave().then((ok) => { if (ok) setSkillOpen(true); }); }}>Edit skills</button><button type="button" disabled={busy} onClick={() => { void readyToLeave().then((ok) => { if (ok) setDiagramOpen(true); }); }}>Manage diagrams</button><button type="button" disabled={busy} onClick={() => { void readyToLeave().then((ok) => { if (ok) setImportOpen(true); }); }}>Import content</button></div>
        {!draft || !record ? (!draft ? <div className="empty-editor"><p className="eyebrow">{names[table]}</p><h1>Choose a record to begin.</h1><p>Edit the form, see the student preview, and run the same checks as the command line.</p></div> : <div className="source-editor"><h1>JSON source</h1><textarea aria-label="Record JSON" value={state.text} onChange={(e) => draft.change(e.target.value)} /></div>) : <>
          <header className="record-header"><div><p className="eyebrow">{names[draft.opened.table]}</p><h1>{title(record)}</h1><p className="record-id">{String(record.id)}</p></div>
            <button type="button" className="primary" disabled={state.saving || state.conflict || !author} onClick={() => void draft.flush()}>{state.saving ? "Saving…" : "Save draft"}</button></header>
          <div className="editor-toolbar"><div className="tabs"><button type="button" aria-pressed={mode === "form"} onClick={() => setMode("form")}>Form</button><button type="button" aria-pressed={mode === "json"} onClick={() => setMode("json")}>JSON source</button></div>
            <span role="status">{state.conflict ? "Conflict · draft retained" : state.saving ? "Saving…" : state.dirty ? "Unsaved changes" : "Saved on this computer"}</span></div>
          <div className="edit-preview"><section className="form-pane" aria-label="Record editor">
            {mode === "json" ? <textarea className="json-source" aria-label="Record JSON" value={state.text} onChange={(e) => draft.change(e.target.value)} /> : <ContractForm readOnlyFields={["review", "version"]} identityEditable={draft.canEditIdentity()} schema={recordSchema(workspace.schema, workspace.definitions[draft.opened.table] ?? "")} root={workspace.schema} value={record} records={allRecords} onChange={(next) => draft.change(JSON.stringify(next, null, 2))} />}
            <details className="duplicate"><summary>Create another draft</summary><Duplicate onDuplicate={(name) => void duplicate(name)} /></details>
            {refs && <details><summary>References · {refs.records.length + refs.skills.length}</summary><ul>{refs.records.map((r) => <li key={r.id}><button type="button" className="quiet" onClick={() => { const row = allRecords.find((item) => item.id === r.id); if (row) void open(row); }}>{r.id}</button></li>)}{refs.skills.map((path) => <li key={path}>{path}</li>)}</ul></details>}
          </section><aside className="preview-pane"><p className="eyebrow">STUDENT PREVIEW</p><Preview report={state.report} record={record} />
            {draft.opened.table === "items" && <Sandbox pack={pack} record={record} author={author} beforeSave={() => draft.flush()} disabled={!state.report?.ok} />}
            {draft.opened.table === "kcs" && <KCGraph pack={pack} record={record} onOpen={(id) => {
              const row = allRecords.find((item) => item.id === id); if (row) void open(row);
            }} />}
            <Checks report={state.report} />
            {draft.opened.table === "worked_examples" && <ExampleTools registerGuard={(guard) => { toolGuard.current = guard; }} key={String(record.id)} pack={pack} record={record} records={allRecords} author={author} beforeSave={() => draft.flush()} onChange={(next) => draft.change(JSON.stringify(next, null, 2))} onCreated={(next) => { install(next); void command<Workspace>({ op: "workspace" }).then(setWorkspace); }} />}
            {draft.opened.table !== "charts_of_accounts" && <><Experiments author={author} beforeSave={() => draft.flush()} pack={pack} table={draft.opened.table} record={record} onOpen={(id) => {
              const row = allRecords.find((item) => item.id === id); if (row) void open(row);
            }} />
            <Workflow pack={draft.opened.pack} table={draft.opened.table} record={record} author={author}
              beforeSave={() => draft.flush()} readRecord={() => object(JSON.parse(draft.getState().text))} onTransition={async () => { setDraft(null); setWorkspace(await command<Workspace>({ op: "workspace" })); setMessage("Authoring pipeline finished. Choose a record to continue."); }} preview={(value) => <Preview record={record} report={{ ok: true, problems: [], preview: value }} />} />
            <Changes schema={workspace.schema} pack={draft.opened.pack} table={draft.opened.table} record={record} author={author} records={allRecords}
              beforeSave={() => draft.flush()} onChanged={async () => { setWorkspace(await command<Workspace>({ op: "workspace" })); setDraft(null); }} /></>}
          </aside></div>
        </>}
        {(state.error || message) && <div className="notice"><ErrorState message={state.error || message} />{state.conflict && <>
          <button type="button" onClick={() => { const link = document.createElement("a"); const url = URL.createObjectURL(new Blob([state.text], { type: "application/json" })); link.href = url; link.download = `${String(draft?.opened.record.id)}.draft.json`; link.click(); URL.revokeObjectURL(url); }}>Download my draft</button>
          <button type="button" disabled={busy} onClick={() => setConfirmReload(true)}>Reload disk version</button></>}</div>}
        <ConfirmDialog open={confirmReload} message="Reload the file from disk?" details={["Download your draft first if you want to keep it."]} confirm="Reload disk version" cancel="Keep my draft" onConfirm={() => void reloadDisk()} onCancel={() => setConfirmReload(false)} />
        {packReport && <section className="pack-report"><h2>CLI pipeline result</h2><Checks report={packReport} /></section>}
      </main></div>{referenceOpen && <ReferenceEditor pack={pack} author={author} registerGuard={(guard) => { modalGuard.current = guard; }} onClose={() => setReferenceOpen(false)} />}
      {skillOpen && <SkillEditor pack={pack} skills={workspace.skills ?? []} author={author} registerGuard={(guard) => { modalGuard.current = guard; }} onClose={() => setSkillOpen(false)} />}{diagramOpen && <DiagramEditor pack={pack} diagrams={(workspace.diagrams ?? []).filter((d) => d.pack === pack)} author={author} registerGuard={(guard) => { modalGuard.current = guard; }} onClose={() => { setDiagramOpen(false); void command<Workspace>({ op: "workspace" }).then(setWorkspace).catch((e: unknown) => setMessage(String(e))); }} />}{importOpen && <BulkImport pack={pack} author={author} registerGuard={(guard) => { modalGuard.current = guard; }} onChanged={async () => setWorkspace(await command<Workspace>({ op: "workspace" }))} onClose={() => setImportOpen(false)} />}<footer className="statusbar"><span>{state.dirty ? "Draft retained in the editor · save before closing" : "Working copy is the source of truth"}</span><span>Local tools · no model required</span></footer>
    </>}
  </div></RegistryProvider></LocaleProvider>;
}
export function Preview({ report, record }: { report: Report | null; record: Data }) {
  const [index, setIndex] = useState(0);
  const preview = object(report?.preview);
  const lesson = preview.lesson as unknown as LessonView | null;
  const example = preview.example as unknown as WorkedExampleView | null;
  useEffect(() => setIndex(0), [record.id]);
  if (example) return <ExampleBoard key={String(record.id)} example={example} />;
  if (lesson) return <LessonPlayerContent view={{ status: "ready", lessonId: lesson.lesson_id, lesson, index: Math.min(index, lesson.blocks.length - 1), checks: {}, positionFailed: false }} actions={{ onGo: setIndex, onAnswer: () => undefined }} />;
  return <div className="plain-preview"><p>{String(record.statement ?? record.title ?? "A preview appears when the record has a valid shape.")}</p>{Array.isArray(record.prerequisites) && <><h3>Prerequisites</h3><ul>{record.prerequisites.map((edge, i) => <li key={i}>{String(object(edge).kc_id)} → {String(object(edge).strength)}</li>)}</ul></>}</div>;
}
function Checks({ report }: { report: Report | null }) {
  return <section className="checks"><h2>{report === null ? "Checking…" : report.ok ? "Checks passed" : "Needs attention"}</h2>{report && <><p className="text-meta">{report.problems.length} problems · {Array.isArray(report.checks) ? report.checks.length : report.checks ?? 0} tool checks</p><ul>{report.problems.map((problem, i) => <li key={i}>{problem}</li>)}</ul>{(Array.isArray(report.checks) ? report.checks : []).map((check) => <details key={check.check_id}><summary>✓ {check.function}</summary><code>{check.check_id}</code><pre>{JSON.stringify(check.value, null, 2)}</pre></details>)}</>}</section>;
}
function Duplicate({ onDuplicate }: { onDuplicate(name: string): void }) {
  const [name, setName] = useState("");
  return <div className="field"><label>New title<input value={name} onChange={(e) => setName(e.target.value)} /></label><button type="button" disabled={!name.trim()} onClick={() => onDuplicate(name)}>Duplicate as a new draft</button></div>;
}
function Sandbox({ pack, record, author, beforeSave, disabled }: { pack: string; record: Data; author: string | null; beforeSave(): Promise<boolean>; disabled: boolean }) {
  const [response, setResponse] = useState(""), [part, setPart] = useState(""), [result, setResult] = useState<unknown>(null);
  const parts = Array.isArray(record.parts) ? record.parts.map(object) : [];
  useEffect(() => setResult(null), [record]);
  const parsed = () => { try { return JSON.parse(response) as unknown; } catch { return response; } };
  const save = async () => { try { if (await beforeSave()) setResult(await command({ op: "golden", pack, id: record.id, author, part: part || parts[0]?.id, response: parsed() })); } catch (error) { setResult(String(error)); } };
  const run = async () => { try { setResult(await command({ op: "mark", pack, record, part: part || parts[0]?.id, response: parsed() })); } catch (error) { setResult(String(error)); } };
  return <section className="sandbox"><h2>Marking sandbox</h2><p className="text-meta">Fictional answers only. The production marker runs locally.</p><label className="field">Part<select value={part || String(parts[0]?.id ?? "")} onChange={(e) => setPart(e.target.value)}>{parts.map((p) => <option key={String(p.id)}>{String(p.id)}</option>)}</select></label><label className="field">Candidate answer<textarea value={response} onChange={(e) => setResponse(e.target.value)} /></label><button type="button" disabled={disabled || !response} onClick={() => void run()}>Run marker</button><button type="button" disabled={disabled || !author || !response} onClick={() => void save()}>Save golden case</button>{result !== null && <pre>{JSON.stringify(result, null, 2)}</pre>}<span className="text-meta">{author ? "Sandbox checks do not change learner data." : "Select an author to save a golden case."}</span></section>;
}
function Bootstrap({ onCreated }: { onCreated(): Promise<void> }) {
  const [name, setName] = useState(""), [email, setEmail] = useState(""), [error, setError] = useState("");
  return <form className="bootstrap" onSubmit={(e) => { e.preventDefault(); void command({ op: "bootstrap", id: "local-author", name, email }).then(onCreated).catch((err: unknown) => setError(String(err))); }}><strong>Set up local authoring</strong><input aria-label="Author name" placeholder="Your name" required value={name} onChange={(e) => setName(e.target.value)} /><input aria-label="Author email" placeholder="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /><button type="submit">Create first author account</button><span>Identity stays in your authoring home.</span>{error && <p role="alert">{error}</p>}</form>;
}
