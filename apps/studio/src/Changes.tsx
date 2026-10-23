import { useEffect, useState } from "react";
import { command } from "./transport.js";
import { ContractForm } from "./Form.js";
import type { Data, Summary, Schema, Json } from "./model.js";

export function Changes({ schema, pack, table, record, author, records, beforeSave, onChanged }: {
  schema?: Schema; pack: string; table: string; record: Data; author: string | null; records: Summary[];
  beforeSave(): Promise<boolean>; onChanged(): Promise<void>;
}) {
  const [result, setResult] = useState<Data | null>(null), [op, setOp] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [version, setVersion] = useState("");
  const [reason, setReason] = useState(""), [replacement, setReplacement] = useState("");
  const [corrections, setCorrections] = useState<Record<string, string>>({}), [migration, setMigration] = useState("[]");
  useEffect(() => { setResult(null); setError(""); setReason(""); setReplacement(""); setOp(""); }, [pack, record.id]);
  const run = async (operation: string, extra: Record<string, unknown> = {}) => {
    setBusy(true); setError("");
    try { if (!await beforeSave()) return; const next = await command<Data>({ op: operation, pack, table, id: record.id, author, ...extra });
      setResult(next); setOp(operation); if (next.applied || next.retired || operation === "set_version" && next.ok) await onChanged(); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const inspectMigration = () => { try { void run("migration", { migrations: JSON.parse(migration) as unknown }); } catch (e) { setError(String(e)); } };
  const changed = result?.changed && typeof result.changed === "object" ? Object.values(result.changed).flat().map(String) : [];
  return <section className="sandbox" aria-label="Release changes"><h2>Release changes</h2>
    <button type="button" disabled={busy} onClick={() => void run("version_plan")}>Calculate version and release notes</button>
    {op === "version_plan" && result?.available === true && <><p>Minimum bump: {String(result.required_bump)} from {String(result.old_version)}</p>
      <label className="field">Release version<input value={version} onChange={(e) => setVersion(e.target.value)} /></label>
      {changed.map((id) => <label className="field" key={id}>Correction for {id}<textarea value={corrections[id] ?? ""} onChange={(e) => setCorrections({ ...corrections, [id]: e.target.value })} /></label>)}
      <button type="button" disabled={busy || !author || !version} onClick={() => void run("set_version", { version, corrections, revision: result.revision })}>Set release version</button></>}
    {table !== "kcs" && <details><summary>Retire this record</summary><p>Update its references first. The retired identity stays reserved.</p>
      <label className="field">Retirement reason<textarea value={reason} onChange={(e) => { setReason(e.target.value); setResult(null); }} /></label>
      <label className="field">Replacement<select value={replacement} onChange={(e) => { setReplacement(e.target.value); setResult(null); }}><option value="">No replacement</option>{records.filter((r) => r.table === table && r.id !== record.id).map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
      <button type="button" disabled={busy || !author || !reason.trim()} onClick={() => void run("retire", { reason, replacement: replacement || null })}>Preview retirement impact</button>
      {op === "retire" && result?.ok === true && !result.retired && <button type="button" disabled={busy} onClick={() => void run("retire", { ...result, reason, replacement: replacement || null, apply: true })}>Apply retirement</button>}</details>}
    {table === "kcs" && <details><summary>KC migration editor</summary><p>Declare source and target KCs with weights summing to one. Preview lists all references and replays fictional event logs through the production projector before applying a major release.</p>
      {schema && <ContractForm schema={{ type: "array", items: { $ref: "#/$defs/KcMigration" } }} root={schema} value={(() => { try { return JSON.parse(migration) as Json; } catch { return []; } })()} records={records} path="$.migrations" onChange={(next) => { setMigration(JSON.stringify(next, null, 2)); setResult(null); }} />}
      <label className="field">Migration rows (JSON)<textarea value={migration} onChange={(e) => { setMigration(e.target.value); setResult(null); }} /></label>
      <button type="button" disabled={busy || !author} onClick={inspectMigration}>Preview migration and replay</button>
      {op === "migration" && result?.ok === true && !result.applied && <button type="button" disabled={busy} onClick={() => void run("migration", { migrations: result.migrations, revisions: result.revisions, apply: true })}>Apply migration</button>}</details>}
    {error && <p role="alert">{error}</p>}
    {result && <div role="status">{result.ok === false || result.available === false ? "Needs attention" : "Result ready"}{Array.isArray(result.problems) && <ul>{result.problems.map((p, i) => <li key={i}>{String(p)}</li>)}</ul>}<pre>{JSON.stringify(result, null, 2)}</pre></div>}
  </section>;
}
