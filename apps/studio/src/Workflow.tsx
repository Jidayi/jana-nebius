import { useEffect, useState, type ReactNode } from "react";
import { EvaluationJobs } from "./EvaluationJobs.js";
import { command } from "./transport.js";
import { object, type Data, type Json } from "./model.js";

export function Workflow({ pack, table, record, author, beforeSave, preview, onTransition, readRecord }: {
  pack: string; table: string; record: Data; author: string | null; beforeSave(): Promise<boolean>;
  preview(value: Json): ReactNode; onTransition?(): Promise<void>; readRecord?(): Data;
}) {
  const [data, setData] = useState<Data>({}), [result, setResult] = useState<Data | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [text, setText] = useState(""), [blocking, setBlocking] = useState(false);
  const [comparison, setComparison] = useState("side-by-side");
  const [anchorKind, setAnchorKind] = useState("record"), [anchor, setAnchor] = useState(""), [parent, setParent] = useState("");
  const load = async () => setData(await command<Data>({ op: "workflow", pack }));
  useEffect(() => { let active = true; setResult(null); setError(""); setText(""); setParent("");
    void command<Data>({ op: "workflow", pack }).then((next) => { if (active) setData(next); }).catch((e: unknown) => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [pack, record.id]);
  const run = async (op: string, extra: Record<string, unknown> = {}) => {
    if (busy) return false;
    setBusy(true); setError("");
    try { if (!await beforeSave()) return false; const next = await command<Data>({ op, pack, table, id: record.id, record: readRecord?.() ?? record, author, ...extra }); setResult(next); await load(); if ((op === "promote" || op === "bank") && next.ok !== false) await onTransition?.(); return next.ok !== false; }
    catch (e) { setError(String(e)); return false; } finally { setBusy(false); }
  };
  const comments = (Array.isArray(data.comments) ? data.comments : []).map(object).filter((c) => c.record_id === record.id);
  return <section className="sandbox" aria-label="Authoring workflow"><h2>Authoring workflow</h2>
    <div className="row"><button type="button" disabled={busy} onClick={() => void run("diff")}>Compare with published</button>
      <button type="button" disabled={busy || !author} onClick={() => void run("evaluate")}>Run local evaluations</button>
      <button type="button" disabled={busy || !author} onClick={() => void run("publish", { channel: "dev" })}>Queue publication</button></div>
    {["items", "lessons", "worked_examples", "misconceptions", "item_templates"].includes(table) && <div className="row"><button type="button" disabled={busy || !author} onClick={() => void run("promote")}>Verify this draft through gates</button><button type="button" disabled={busy || !author} onClick={() => void run("bank")}>Move verified pack to evaluation bank</button></div>}
    <p>Publication needs a committed, evaluated version and no open blocking comments. The signing service rebuilds and checks queued requests.</p>
    <details><summary>Comments · {comments.length}</summary>
      {comments.map((c) => <article key={String(c.id)}><p><strong>{c.blocking ? "Blocking" : "Comment"} · {String(c.status)}</strong> · {String(object(c.anchor).kind)} {String(object(c.anchor).value)}</p>
        <p>{String(c.text)}</p>{c.parent && <p>Reply to {String(c.parent)}</p>}
        <button type="button" disabled={busy || !author} onClick={() => setParent(String(c.id))}>Reply</button>
        {c.status === "open" && <button type="button" disabled={busy || !author} onClick={() => void run("comment", { resolve: c.id })}>Resolve comment</button>}</article>)}
      <label className="field">Anchor type<select value={anchorKind} onChange={(e) => setAnchorKind(e.target.value)}>{(table === "skills" ? ["record", "field", "skill_line"] : ["record", "field", "step", "part"]).map((kind) => <option key={kind}>{kind}</option>)}</select></label>
      {anchorKind !== "record" && <label className="field">Anchor<input value={anchor} onChange={(e) => setAnchor(e.target.value)} /></label>}
      <label className="field">Author comment<textarea value={text} onChange={(e) => setText(e.target.value)} /></label>
      <label><input type="checkbox" checked={blocking} onChange={(e) => setBlocking(e.target.checked)} /> Blocks publication</label>
      {parent && <p>Replying to {parent} <button type="button" onClick={() => setParent("")}>Cancel reply</button></p>}
      <button type="button" disabled={busy || !author || !text.trim()} onClick={() => void run("comment", { text, blocking, parent: parent || null, anchor: { kind: anchorKind, value: anchorKind === "record" ? record.id : anchor } }).then((ok) => { if (ok) setText(""); })}>Add comment</button>
    </details>
    {error && <p role="alert">{error}</p>}
    {result && <div role="status">{result.available === false || result.ok === false ? "Needs attention" : "Result ready"}
      {Array.isArray(result.marking_changed) && result.marking_changed.length > 0 && <p><strong>Changes marking — needs a major version</strong></p>}
      {Array.isArray(result.problems) && <ul>{result.problems.map((p, i) => <li key={i}>{String(p)}</li>)}</ul>}
      {Array.isArray(result.fields) && <><h3>Field changes from published commit {String(result.commit).slice(0, 8)}</h3><pre>{JSON.stringify(result.fields, null, 2)}</pre></>}
      {result.before_preview && <><label className="field">Rendered comparison<select value={comparison} onChange={(e) => setComparison(e.target.value)}><option value="side-by-side">Side by side</option><option value="overlay">Overlay</option></select></label><div className={`published-comparison ${comparison === "overlay" ? "comparison-overlay" : ""}`}><div><h3>Published</h3>{preview(result.before_preview)}</div><div><h3>Current draft</h3>{preview(result.after_preview ?? null)}</div></div></>}
      <details><summary>Full result</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div>}
    <EvaluationJobs pack={pack} table={table} id={String(record.id)} author={author} beforeSave={beforeSave} />
  </section>;
}
