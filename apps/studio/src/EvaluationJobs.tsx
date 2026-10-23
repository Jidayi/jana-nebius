import { useEffect, useState } from "react";
import { command } from "./transport.js";
import { object, type Data } from "./model.js";
export function EvaluationJobs({ pack, table, id, author, beforeSave }: {
  pack: string; table: string; id: string; author: string | null; beforeSave(): Promise<boolean>;
}) {
  const [jobs, setJobs] = useState<Data[]>([]), [personas, setPersonas] = useState<string[]>([]), [selected, setSelected] = useState<string[]>([]);
  const [count, setCount] = useState(5), [items, setItems] = useState(""), [result, setResult] = useState<Data | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const load = async () => { const value = await command<Data>({ op: "workflow", pack }); setJobs((Array.isArray(value.jobs) ? value.jobs : []).map(object)); };
  useEffect(() => { let active = true;
    void command<Data>({ op: "workflow", pack }).then((v) => { if (active) setJobs((Array.isArray(v.jobs) ? v.jobs : []).map(object)); }).catch((e: unknown) => { if (active) setError(String(e)); });
    void command<{ personas?: string[] }>({ op: "job_personas" }).then((v) => { if (active) { setPersonas(v.personas ?? []); setSelected(v.personas ?? []); } }).catch((e: unknown) => { if (active) setError(String(e)); });
    setResult(null); return () => { active = false; };
  }, [pack, id]);
  const run = async (op: string, extra: Record<string, unknown> = {}) => { setBusy(true); setError("");
    try { if (!await beforeSave()) return; setResult(await command<Data>({ op, pack, table, id, author, ...extra })); await load(); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const visible = jobs.filter((job) => !job.target || job.target === id);
  return <section className="sandbox" aria-label="Evaluation jobs"><h2>Evaluation jobs</h2>
    <p>Requests stay on this computer until a trusted local evaluation runtime is configured. Runs use fictional development data. Calibrated rubric judging and candidate acceptance remain separate.</p>
    {["items", "lessons", "skills"].includes(table) && <details><summary>Simulated students</summary><fieldset><legend>Personas</legend>{personas.map((p) => <label key={p}><input type="checkbox" checked={selected.includes(p)} onChange={(e) => setSelected(e.target.checked ? [...selected, p] : selected.filter((v) => v !== p))} />{p.replaceAll("_", " ")}</label>)}</fieldset>
      <label className="field">Runs per persona<input type="number" min={1} max={20} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label>
      {table === "skills" && <label className="field">Simulation item ids (one per line)<textarea value={items} onChange={(e) => setItems(e.target.value)} /></label>}
      <button type="button" disabled={busy || !author || !selected.length || count < 1 || count > 20} onClick={() => void run("job_queue", { kind: "simulation", personas: selected, count, ...(items.trim() ? { item_ids: items.trim().split(/\s+/) } : {}) })}>Queue simulated students</button></details>}
    <button type="button" disabled={busy} onClick={() => { void load().catch((e: unknown) => setError(String(e))); }}>Refresh evaluation jobs</button>
    <ul>{visible.map((job) => <li key={String(job.id)}>{String(job.kind)} · {String(job.id)} <button type="button" disabled={busy || !author} onClick={() => void run("job_start", { job_id: job.id })}>Start local job {String(job.id).slice(-6)}</button><button type="button" disabled={busy} onClick={() => void run("job_result", { job_id: job.id })}>Read result {String(job.id).slice(-6)}</button></li>)}</ul>
    {error && <p role="alert">{error}</p>}{result && <div role="status">{result.current === false && <p>Inputs changed. This result is retained as historical evidence; queue a new run for the current draft.</p>}
      {result.message && <p>{String(result.message)}</p>}{Array.isArray(result.problems) && <ul>{result.problems.map((p, i) => <li key={i}>{String(p)}</li>)}</ul>}
      <details open><summary>Transcript, checks and rubric status</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div>}
  </section>;
}
