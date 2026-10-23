import { useState } from "react";
import { branchOf, childSchema, initial, initialVariant, object, schemaOf, variantIndex, variantsOf, type Json, type Schema, type Summary } from "./model.js";
const labelOf = (key: string) => key.replaceAll("_", " ");
function infer(value: Json | undefined): Schema {
  return { type: Array.isArray(value) ? "array" : value === null ? "null" : typeof value === "object" ? "object" : typeof value };
}
export function ContractForm({ schema, root, value, onChange, records, path = "$", depth = 0, identityEditable = false, readOnlyFields = [] }: {
  schema: Schema; root: Schema; value: Json | undefined; onChange(value: Json): void; records: Summary[]; path?: string; depth?: number; identityEditable?: boolean; readOnlyFields?: string[];
}) {
  const [extra, setExtra] = useState("");
  const base = schemaOf(schema, root), s = branchOf(schema, value, root);
  const variants = variantsOf(base);
  const props = s.properties ?? {};
  const type = s.type ?? infer(value).type;
  const field = path.split(".").at(-1) ?? path;
  const change = (key: string, child: Json) => onChange({ ...object(value), [key]: child });
  if (depth > 64) return <textarea aria-label={`${path} JSON`} value={JSON.stringify(value ?? null)} onChange={(e) => { try { onChange(JSON.parse(e.target.value) as Json); } catch { onChange(e.target.value); } }} />;
  const branchPicker = variants && <label className="field">Variant<select aria-label={`${path} variant`} value={variantIndex(base, value, root)} onChange={(e) => onChange(initialVariant(base, Number(e.target.value), root))}>
    {variants.map((variant, i) => { const v = schemaOf(variant, root); const tag = Object.values(v.properties ?? {}).find((p) => p.const !== undefined)?.const;
      return <option key={i} value={i}>{String(tag ?? v.type ?? i + 1)}</option>; })}</select></label>;
  let control;
  if (s.enum || s.const !== undefined) {
    const options = s.enum ?? [s.const ?? null];
    control = <select aria-label={path} value={JSON.stringify(value)} onChange={(e) => onChange(JSON.parse(e.target.value) as Json)}>{options.map((option) => <option key={JSON.stringify(option)} value={JSON.stringify(option)}>{String(option)}</option>)}</select>;
  } else if (type === "object" || !type && s.properties) {
    const data = object(value), known = { ...props };
    for (const key of Object.keys(data)) known[key] ??= childSchema(s, key);
    control = <div className="fields">{Object.entries(known).filter(([key]) => key in data || s.required?.includes(key)).map(([key, child]) =>
      <div key={key} className="field-group"><div className="field-name"><span>{labelOf(key)}{s.required?.includes(key) ? " *" : ""}</span>
        {!s.required?.includes(key) && !(key === "id" && path === "$") && <button type="button" className="quiet" aria-label={`Remove ${path}.${key}`} onClick={() => { onChange(Object.fromEntries(Object.entries(data).filter(([name]) => name !== key))); }}>Remove</button>}</div>
        {path === "$" && (readOnlyFields.includes(key) || key === "id" && !identityEditable) ? <div data-field-path={`${path}.${key}`}><code>{typeof data[key] === "object" ? JSON.stringify(data[key]) : String(data[key])}</code><p className="text-meta">Managed by identity, migration or review controls.</p></div> : <ContractForm schema={child} root={root} value={data[key]} onChange={(next) => change(key, next)} records={records} path={`${path}.${key}`} depth={depth + 1} />}
      </div>)}
      {Object.keys(props).some((key) => !(key in data)) && <label className="field">Add a field<select aria-label={`Add field to ${path}`} value="" onChange={(e) => { const key = e.target.value; if (key) change(key, initial(props[key] ?? {}, root)); }}><option value="">Choose a field…</option>{Object.keys(props).filter((key) => !(key in data)).map((key) => <option key={key}>{key}</option>)}</select></label>}
      {(s.additionalProperties !== false || s.patternProperties) && <div className="row"><input aria-label={`New key in ${path}`} value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="New key" /><button type="button" disabled={!extra || extra in data || s.additionalProperties === false && !Object.keys(s.patternProperties ?? {}).some((pattern) => new RegExp(pattern).test(extra))} onClick={() => { change(extra, initial(childSchema(s, extra), root)); setExtra(""); }}>Add key</button></div>}
    </div>;
  } else if (type === "array" || Array.isArray(value)) {
    const data = Array.isArray(value) ? value : [];
    const move = (from: number, to: number) => { const next = [...data]; const [entry] = next.splice(from, 1); if (entry !== undefined) next.splice(to, 0, entry); onChange(next); };
    control = <div className="array">{data.map((entry, i) => <details key={i} open={data.length < 5}><summary>{i + 1}. {String(object(entry).type ?? object(entry).name ?? object(entry).id ?? labelOf(field))}</summary>
      <div className="row"><button type="button" disabled={i === 0} aria-label={`Move ${path}[${i}] up`} onClick={() => move(i, i - 1)}>Move up</button><button type="button" disabled={i === data.length - 1} aria-label={`Move ${path}[${i}] down`} onClick={() => move(i, i + 1)}>Move down</button><button type="button" aria-label={`Remove ${path}[${i}]`} onClick={() => onChange(data.filter((_, n) => n !== i))}>Remove</button></div>
      <ContractForm schema={s.items ?? {}} root={root} value={entry} onChange={(next) => onChange(data.map((old, n) => i === n ? next : old))} records={records} path={`${path}[${i}]`} depth={depth + 1} />
    </details>)}<button type="button" disabled={s.maxItems !== undefined && data.length >= s.maxItems} onClick={() => onChange([...data, initial(s.items ?? {}, root)])}>Add {labelOf(field)}</button></div>;
  } else if (type === "boolean") control = <input aria-label={path} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />;
  else if (type === "number" || type === "integer") control = <input aria-label={path} inputMode="decimal" value={String(value ?? "")} onChange={(e) => onChange(e.target.value === "" || !Number.isFinite(Number(e.target.value)) ? e.target.value : Number(e.target.value))} />;
  else if (type === "null") control = <output aria-label={path}>null</output>;
  else {
    const choices = records.filter((r) => (schema.$ref?.includes("KcId") && r.table === "kcs") ||
      (schema.$ref?.includes("NodeId") && r.table === "curriculum_nodes") ||
      (schema.$ref?.includes("ItemId") && r.table === "items") ||
      (schema.$ref?.includes("WorkedExampleId") && r.table === "worked_examples") ||
      (schema.$ref?.includes("MisconceptionId") && r.table === "misconceptions"));
    control = choices.length ? <><input list={path} aria-label={path} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} /><datalist id={path}>{choices.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</datalist></> :
      <textarea aria-label={path} rows={String(value ?? "").length > 160 ? 4 : 2} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
  }
  const anyType = !base.type && !base.properties && !base.enum && base.const === undefined && !variants;
  return <>{branchPicker}{anyType && <label className="field">Value type<select aria-label={`${path} type`} value={Array.isArray(value) ? "array" : value === null ? "null" : typeof value === "undefined" ? "string" : typeof value} onChange={(e) => onChange(initial({ type: e.target.value }, root))}>{["string", "number", "boolean", "object", "array", "null"].map((kind) => <option key={kind}>{kind}</option>)}</select></label>}{control}</>;
}
export function recordSchema(root: Schema, definition: string): Schema {
  const s = root.$defs?.[definition] ?? {};
  return { ...s, properties: { ...s.properties, checks: s.properties?.checks ?? { type: "object" }, authoring: s.properties?.authoring ?? { type: "object" } } };
}
