import { useEffect, useState } from "react";
import { command } from "./transport.js";
import { object, type Data, type Json } from "./model.js";

export function Experiments({ pack, table, record, onOpen, author = null, beforeSave = async () => true }: { pack: string; table: string; record: Data; onOpen(id: string): void; author?: string | null; beforeSave?(): Promise<boolean> }) {
  const [result, setResult] = useState<Data | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { setResult(null); setError(""); }, [pack, record]);
  if (table !== "misconceptions" && table !== "item_templates") return null;
  const bench = table === "misconceptions";
  const run = async () => {
    setBusy(true); setError("");
    try { setResult(await command<Data>({ op: bench ? "signature_bench" : "sample_template", pack, record })); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const rows = (Array.isArray(result?.[bench ? "items" : "variants"]) ? result[bench ? "items" : "variants"] : []) as Json[];
  return <section className="sandbox" aria-label={bench ? "Signature test bench" : "Template sampler"}>
    <h2>{bench ? "Signature test bench" : "Template sampler"}</h2>
    <p>{bench ? "Test the current signature against every item sharing its knowledge components. Conditional signatures show the evidence they need." : "Sample up to 50 variants across the declared ranges. The named answer tool computes every key; constraints and tool failures stay visible."}</p>
    <button type="button" disabled={busy} onClick={() => void run()}>{busy ? "Running tools…" : bench ? "Run signature bench" : "Generate 50 samples"}</button>
    {!bench && <button type="button" disabled={busy || !author || result?.ok !== true} onClick={() => { void (async () => { if (!await beforeSave()) return; setBusy(true); try { setResult(await command<Data>({ op: "template_review_ranges", pack, id: record.id, author })); } catch (e) { setError(String(e)); } finally { setBusy(false); } })(); }}>Record reviewed parameter ranges</button>}
    {result?.reviewed_ranges && <p>Parameter ranges recorded. Generated drafts still require publication checks.</p>}
    {error && <p role="alert">{error}</p>}
    {result && <div role="status">{result.ok ? "Run completed" : "Needs attention"}{Array.isArray(result.problems) && <ul>{result.problems.map((p, i) => <li key={i}>{String(p)}</li>)}</ul>}</div>}
    {result && !bench && <details><summary>Key distribution</summary><pre>{JSON.stringify(result.distribution, null, 2)}</pre></details>}
    {result && bench && Array.isArray(result.collisions) && <><h3>Collisions · {result.collisions.length}</h3><ul>{result.collisions.map((c, i) => { const row = object(c); return <li key={i}><button type="button" onClick={() => onOpen(String(row.item_id))}>{String(row.item_id)}</button> · {String(row.part)} · {JSON.stringify(row.misconceptions)} → {String(row.wrong_answer)}</li>; })}</ul></>}
    {rows.map((value, i) => { const row = object(value); return <details key={i}><summary>{bench ? `${String(row.item_id)} · ${String(row.part)}` : `Sample ${i + 1} · ${row.ok ? "Verified key" : "Needs attention"}`}</summary>
      {bench && <button type="button" onClick={() => onOpen(String(row.item_id))}>Open item</button>}
      {!bench && <p>{String(row.stem ?? "")}</p>}
      <pre>{JSON.stringify(row, null, 2)}</pre></details>; })}
  </section>;
}
