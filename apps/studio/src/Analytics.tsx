import { useState } from "react";
import { command } from "./transport.js";
import { object, type Data, type Json, type Opened } from "./model.js";

// AUT-37, AUT-38, CUR-26, ASM-21: what authors see of evaluation runs and consented research exports (per-record
// figures with sample size and 95% interval; nothing below the student minimum), the internal review queue, and
// content problem reports by category. Nothing here edits a record: a report or queue entry opens a draft change.
const TABLES: Record<string, string> = { itm: "items", wex: "worked_examples", les: "lessons", kc: "kcs", mc: "misconceptions", itpl: "item_templates", mck: "mock_papers" };
const OUTCOMES: [string, string][] = [["needs_edit", "Needs an edit"], ["wrong_key", "Wrong key"], ["unsafe", "Unsafe content"], ["dismissed", "No problem"]];
const packOf = (id: string) => `pack.${id.split(".").slice(1, 3).join(".")}`;
const rows = (value: Json | undefined) => (Array.isArray(value) ? value : []).map(object);
function Figure({ label, value }: { label: string; value: Json | undefined }) {
  const shown = object(value), interval = Array.isArray(shown.interval) ? shown.interval.map(Number) : null;
  return <li>{label}: {shown.value === undefined ? "—" : `${Number(shown.value).toFixed(3)} (95% ${interval?.[0]?.toFixed(3)} to ${interval?.[1]?.toFixed(3)})`}</li>;
}
function Statistics({ stats }: { stats: Data }) {
  return <ul className="text-meta"><li>{String(stats.students)} students · {String(stats.responses)} responses</li>
    {stats.suppressed ? <li>Too few students to show figures.</li> : <><Figure label="Facility" value={stats.facility} /><Figure label="Discrimination" value={stats.discrimination} />
      {Object.entries(object(stats.distractors)).map(([option, value]) => { const pick = object(value); return <Figure key={option} label={`Option ${option}`} value={{ value: pick.share ?? null, interval: pick.interval ?? null }} />; })}</>}</ul>;
}
export function Analytics({ pack, author, onOpen }: { pack: string; author: string | null; onOpen(opened: Opened): Promise<void> }) {
  const [queue, setQueue] = useState<Data[] | null>(null), [inbox, setInbox] = useState<Data[]>([]), [records, setRecords] = useState<Data[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const run = async (work: () => Promise<void>) => { setBusy(true); setError(""); try { await work(); } catch (e) { setError(String(e)); } finally { setBusy(false); } };
  const load = () => run(async () => {
    const [q, i, r] = await Promise.all([command<Data>({ op: "analytics_queue", author }), command<Data>({ op: "inbox_list", author }), command<Data>({ op: "analytics_records", pack, author })]);
    setQueue(rows(q.entries)); setInbox(rows(i.rows)); setRecords(rows(r.records));
  });
  const resolve = (id: string, outcome: string) => run(async () => { await command({ op: "analytics_resolve", id, outcome, author }); setQueue(rows((await command<Data>({ op: "analytics_queue", author })).entries)); });
  const draft = (id: string) => run(async () => { await onOpen(await command<Opened>({ op: "inbox_open", pack: packOf(id), table: TABLES[id.split(".")[0] ?? ""] ?? "items", id, author })); });
  return <section className="pack-report" aria-label="Analytics and reports"><h2>Analytics and reports</h2>
    <p className="text-meta">From evaluation runs and consented research exports only. No student rows or conversations reach the studio.</p>
    <button type="button" disabled={busy || !author} onClick={() => void load()}>Refresh analytics</button>{!author && <span className="text-meta"> Select an author to read analytics.</span>}
    {queue && <><h3>Review queue · {queue.filter((e) => e.status === "open").length} open</h3><ul>{queue.map((entry) => { const id = String(entry.record_id); return <li key={id}><strong>{id}</strong> · {String(entry.status)} · {(Array.isArray(entry.reasons) ? entry.reasons : []).map(String).join(", ")}
      <Statistics stats={object(entry.statistics)} />{object(entry.calibration).replaced === true && <p className="text-meta">Calibrated difficulty {String(object(entry.calibration).difficulty)} (author's {String(object(entry.calibration).prior)})</p>}
      {entry.status === "open" && OUTCOMES.map(([outcome, label]) => <button type="button" key={outcome} disabled={busy} onClick={() => void resolve(id, outcome)}>{label}</button>)}
      <button type="button" disabled={busy} onClick={() => void draft(id)}>Open draft change on {id}</button></li>; })}</ul></>}
    {queue && <><h3>Content problem reports</h3>{inbox.length === 0 ? <p>No reports.</p> : <ul>{inbox.map((row) => { const id = String(row.record_id); return <li key={id}><strong>{id}</strong> · {Object.entries(object(row.counts)).map(([category, n]) => `${category.replaceAll("_", " ")} ${String(n)}`).join(" · ")}
      {rows(row.notes).map((note, n) => <blockquote key={n}>{String(note.note)}</blockquote>)}<button type="button" disabled={busy} onClick={() => void draft(id)}>Open draft change on {id}</button></li>; })}</ul>}
      <h3>Items in this pack</h3>{records.length === 0 ? <p>No statistics yet.</p> : <ul>{records.map((stats) => <li key={String(stats.record_id)}>{String(stats.record_id)}<Statistics stats={stats} /></li>)}</ul>}</>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
