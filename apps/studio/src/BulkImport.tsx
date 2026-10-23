import { useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "@jana/ui";
import { command } from "./transport.js";
import { object, type Data } from "./model.js";
const fields = ["title", "url", "licence", "attribution", "modifications", "retrieved"] as const;
export function BulkImport({ pack, author, registerGuard, onChanged, onClose }: {
  pack: string; author: string | null; registerGuard(guard: () => Promise<boolean>): void;
  onChanged(): Promise<void>; onClose(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null), [format, setFormat] = useState("yaml"), [table, setTable] = useState("items");
  const [text, setText] = useState(""), [source, setSource] = useState<Record<string, string>>({}), [preview, setPreview] = useState<Data | null>(null);
  const [result, setResult] = useState<Data | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false), [discard, setDiscard] = useState(false), [dirty, setDirty] = useState(false);
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => { registerGuard(async () => { if (dirty) setError("Finish or discard this import before closing."); return !dirty; }); return () => registerGuard(async () => true); }, [dirty]);
  useEffect(() => { const before = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); }; window.addEventListener("beforeunload", before); return () => window.removeEventListener("beforeunload", before); }, [dirty]);
  const changed = () => { setDirty(true); setPreview(null); setResult(null); setError(""); };
  const run = async (apply: boolean) => {
    setBusy(true); setError("");
    try { const next = await command<Data>({ op: apply ? "import_apply" : "import_preview", pack, table, format, text, source, author, ...(apply ? { preview_sha256: preview?.preview_sha256 } : {}) });
      if (apply) { setResult(next); if (next.ok) { setDirty(false); await onChanged(); } } else setPreview(next);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const close = () => { if (dirty) setDiscard(true); else onClose(); };
  const problems = Array.isArray(preview?.problems) ? preview.problems.map(object) : [];
  return <dialog ref={dialog} className="skill-dialog" aria-label="Bulk content import" onCancel={(e) => { e.preventDefault(); close(); }}><div className="row"><h1>Import content</h1><button type="button" disabled={busy} onClick={close}>Close import</button></div>
    <p>Run a dry run before importing. Every row needs an external reference and complete source and licence details. Imports create drafts; answer verification and publication gates still apply.</p>
    <label className="field">Content type<select value={table} disabled={busy} onChange={(e) => { changed(); setTable(e.target.value); }}>{["items", "kcs", "misconceptions"].map((v) => <option key={v}>{v}</option>)}</select></label>
    <label className="field">Source format<select value={format} disabled={busy} onChange={(e) => { changed(); setFormat(e.target.value); }}><option value="yaml">YAML records</option><option value="csv">CSV</option></select></label>
    <label className="field">Read a local source file<input type="file" accept=".yaml,.yml,.csv,text/csv" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 512 * 1024) { setError("Choose a file no larger than 512 KiB."); return; } void file.text().then((value) => { changed(); setText(value); }).catch((err: unknown) => setError(String(err))); }} /></label>
    <label className="field">Import source<textarea rows={14} disabled={busy} value={text} onChange={(e) => { changed(); setText(e.target.value); }} /></label>
    <details><summary>Shared source details (rows may override these)</summary>{fields.map((name) => <label className="field" key={name}>Source {name}{name === "licence" ? <select value={source[name] ?? ""} onChange={(e) => { changed(); setSource({ ...source, [name]: e.target.value }); }}><option value="">Choose an allowed licence</option>{["CC0-1.0", "CC-BY-3.0", "CC-BY-4.0", "LicenseRef-PublicDomain", "LicenseRef-Own"].map((v) => <option key={v}>{v}</option>)}</select> : <input type={name === "retrieved" ? "date" : "text"} value={source[name] ?? ""} onChange={(e) => { changed(); setSource({ ...source, [name]: e.target.value }); }} />}</label>)}</details>
    <button type="button" disabled={busy || !text.trim()} onClick={() => void run(false)}>Run import dry run</button>
    {preview && <section aria-label="Import dry run"><h2>{preview.ok ? "Dry run passed" : "Fix import errors"}</h2><p>{Array.isArray(preview.records) ? preview.records.length : 0} records</p>
      {problems.length > 0 && <table><thead><tr><th>Row</th><th>Column</th><th>Problem</th></tr></thead><tbody>{problems.map((p, i) => <tr key={i}><td>{String(p.row)}</td><td>{String(p.column)}</td><td>{String(p.message)}</td></tr>)}</tbody></table>}
      <button type="button" disabled={busy || !author || preview.ok !== true} onClick={() => void run(true)}>Import verified dry run as drafts</button></section>}
    {result && <div role="status"><pre>{JSON.stringify(result, null, 2)}</pre></div>}
    {error && <p role="alert">{error}</p>}<ConfirmDialog open={discard} message="Discard this unimported source?" details={[]} confirm="Discard import draft" cancel="Keep import draft" onConfirm={onClose} onCancel={() => setDiscard(false)} />
  </dialog>;
}
