import { useEffect, useState } from "react";
import { command } from "./transport.js";
import { object, type Data, type Opened, type Summary } from "./model.js";

export function ExampleTools({ pack, record, records, beforeSave, onChange, onCreated, author, registerGuard }: {
  pack: string; record: Data; records: Summary[]; author: string | null; beforeSave(): Promise<boolean>;
  registerGuard(guard: () => Promise<boolean>): void; onChange(record: Data): void; onCreated(opened: Opened): void;
}) {
  const [drag, setDrag] = useState<number | null>(null), [template, setTemplate] = useState("");
  const [sample, setSample] = useState(0), [identity, setIdentity] = useState(""), [recipe, setRecipe] = useState("");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => { registerGuard(async () => { if (recipe) setError("Create or discard the authored variant recipe before leaving."); return !recipe; }); return () => registerGuard(async () => true); }, [recipe]);
  useEffect(() => { const before = (e: BeforeUnloadEvent) => { if (recipe) e.preventDefault(); }; window.addEventListener("beforeunload", before); return () => window.removeEventListener("beforeunload", before); }, [recipe]);
  const steps = Array.isArray(record.steps) ? record.steps.map(object).map((s) => Number(s.n)) : [];
  const order = Array.isArray(record.fading_order) ? record.fading_order.map(Number) : [];
  const move = (from: number, to: number) => { const next = [...order]; const [value] = next.splice(from, 1); if (value !== undefined) next.splice(to, 0, value); onChange({ ...record, fading_order: next }); };
  const create = async () => {
    setBusy(true); setError("");
    try { if (!await beforeSave()) return; const result = await command<Data>({ op: "template_variant", pack, id: record.id, template_id: template, sample, new_id: identity, recipe: JSON.parse(recipe), author });
      if (result.ok) { setRecipe(""); onCreated(result.opened as unknown as Opened); } else setError(JSON.stringify(result.problems));
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return <section className="sandbox" aria-label="Worked example tools"><h2>Worked example tools</h2><p>Blank steps in this order. Drag a row or use its move buttons. Only existing steps can be selected.</p>
    <ol>{order.map((n, i) => <li key={i} draggable onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); if (drag !== null) move(drag, i); setDrag(null); }}>Step {n} <button type="button" disabled={i === 0} onClick={() => move(i, i - 1)}>Move step {n} earlier</button><button type="button" disabled={i === order.length - 1} onClick={() => move(i, i + 1)}>Move step {n} later</button><button type="button" onClick={() => onChange({ ...record, fading_order: order.filter((_, j) => j !== i) })}>Remove step {n} from fading</button></li>)}</ol>
    <label className="field">Add fading step<select value="" onChange={(e) => { if (e.target.value) onChange({ ...record, fading_order: [...order, Number(e.target.value)] }); }}><option value="">Choose an existing step</option>{steps.filter((n) => !order.includes(n)).map((n) => <option key={n} value={n}>Step {n}</option>)}</select></label>
    <details><summary>Create a variant from a template</summary><p>Supply an authored JSON recipe containing steps, checks, final_answer and fading_order. Use parameter placeholders and {'{key}'} for the computed key. Double literal maths braces. The verifier recomputes every check before creating a new draft.</p>
      <label className="field">Variant template<select value={template} onChange={(e) => setTemplate(e.target.value)}><option value="">Choose a template</option>{records.filter((r) => r.table === "item_templates").map((r) => <option key={r.id}>{r.id}</option>)}</select></label>
      <label className="field">Sample index (0–49)<input type="number" min={0} max={49} value={sample} onChange={(e) => setSample(Number(e.target.value))} /></label>
      <label className="field">New worked example id<input value={identity} onChange={(e) => setIdentity(e.target.value)} /></label>
      <label className="field">Authored variant recipe<textarea rows={12} value={recipe} onChange={(e) => setRecipe(e.target.value)} /></label>
      <button type="button" disabled={busy || !author || !template || !identity || !recipe} onClick={() => void create()}>Verify and create variant draft</button>
      {recipe && <button type="button" onClick={() => setRecipe("")}>Discard variant recipe</button>}
    </details>{error && <p role="alert">{error}</p>}
  </section>;
}
