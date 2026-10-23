export type Json = string | number | boolean | null | Json[] | Data;
export interface Data { [key: string]: Json }
export interface Schema {
  $ref?: string; $defs?: Record<string, Schema>; type?: string | string[]; properties?: Record<string, Schema>;
  required?: string[]; items?: Schema; oneOf?: Schema[]; anyOf?: Schema[]; allOf?: Schema[];
  if?: Schema; then?: Schema; else?: Schema; patternProperties?: Record<string, Schema>; minItems?: number; maxItems?: number; minimum?: number;
  enum?: Json[]; const?: Json; default?: Json; additionalProperties?: boolean | Schema; description?: string;
}
export interface Summary { id: string; title: string; table: string; node_id: string | null; code: string | null }
export interface Pack { id: string; subject: string; level: string; records: Summary[] }
export interface Workspace {
  root: string; packs: Pack[]; tables: string[]; schema: Schema; definitions: Record<string, string>;
  accounts: { id: string; name: string; roles: string[] }[]; author: string | null;
  skills?: { name: string; kind: string; path: string }[];
  diagrams?: { pack: string; id: string; title: string }[];
}
export interface Opened { new?: boolean; pack: string; table: string; path: string; revision: string; record: Data }
export interface Report { ok: boolean; problems: string[]; schema_problems?: string[];
  checks?: { check_id: string; function: string; value: Json }[]; preview?: Json }
export type Command = <T>(request: Record<string, unknown>) => Promise<T>;
export class StudioError extends Error { constructor(readonly code: string, message: string) { super(message); } }
export function object(value: Json | undefined): Data { return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {}; }
const typeOf = (value: Json | undefined) => value === null ? "null" : Array.isArray(value) ? "array" : typeof value;
function merge(a: Schema, b: Schema): Schema {
  const properties = { ...a.properties };
  for (const [key, value] of Object.entries(b.properties ?? {})) properties[key] = properties[key] ? merge(properties[key] ?? {}, value) : value;
  return { ...a, ...b, ...(a.properties || b.properties ? { properties } : {}),
    ...(a.required || b.required ? { required: [...new Set([...(a.required ?? []), ...(b.required ?? [])])] } : {}),
    ...(a.items && b.items ? { items: merge(a.items, b.items) } : {}) };
}
export function schemaOf(schema: Schema, root: Schema): Schema {
  let current = schema; const seen = new Set<string>();
  while (current.$ref?.startsWith("#/") && !seen.has(current.$ref)) {
    seen.add(current.$ref); let found: unknown = root;
    for (const key of current.$ref.slice(2).split("/").map((s) => s.replaceAll("~1", "/").replaceAll("~0", "~"))) found = typeof found === "object" && found !== null ? (found as Record<string, unknown>)[key] : undefined;
    if (typeof found !== "object" || found === null) break;
    const { $ref: _ref, ...siblings } = current;
    current = merge(found as Schema, siblings);
  }
  return current;
}
export function variantsOf(schema: Schema): Schema[] | undefined {
  return schema.oneOf ?? schema.anyOf ?? (Array.isArray(schema.type) ? schema.type.map((type) => ({ ...schema, type })) : undefined);
}
function matches(schema: Schema, value: Json | undefined, root: Schema): boolean {
  const s = schemaOf(schema, root), data = object(value);
  if (s.const !== undefined && JSON.stringify(value) !== JSON.stringify(s.const)) return false;
  if (s.enum && !s.enum.some((option) => JSON.stringify(option) === JSON.stringify(value))) return false;
  if (s.type && !(Array.isArray(s.type) ? s.type : [s.type]).some((type) => type === typeOf(value) || type === "integer" && typeof value === "number" && Number.isInteger(value))) return false;
  if (value !== null && typeof value === "object" && !Array.isArray(value) && s.required?.some((key) => !(key in data))) return false;
  if (value !== null && typeof value === "object" && !Array.isArray(value) && Object.entries(s.properties ?? {}).some(([key, child]) => key in data && !matches(child, data[key], root))) return false;
  if (s.anyOf && !s.anyOf.some((child) => matches(child, value, root))) return false;
  if (s.oneOf && s.oneOf.filter((child) => matches(child, value, root)).length !== 1) return false;
  if (Array.isArray(value) && s.items && value.some((entry) => !matches(s.items ?? {}, entry, root))) return false;
  return !s.allOf?.some((child) => !matches(child, value, root));
}
export function variantIndex(schema: Schema, value: Json | undefined, root: Schema): number {
  const variants = variantsOf(schema) ?? [];
  const tagged = variants.findIndex((v) => Object.entries(schemaOf(v, root).properties ?? {}).some(([key, child]) => child.const !== undefined && object(value)[key] === child.const));
  if (tagged >= 0) return tagged;
  const matching = variants.findIndex((v) => matches(v, value, root));
  return matching >= 0 ? matching : 0;
}
export function branchOf(schema: Schema, value: Json | undefined, root: Schema): Schema {
  let base = schemaOf(schema, root);
  const variants = variantsOf(base);
  if (variants) {
    const { oneOf: _one, anyOf: _any, ...common } = base;
    base = merge(common, schemaOf(variants[variantIndex(base, value, root)] ?? {}, root));
  }
  for (const clause of base.allOf ?? []) {
    const c = schemaOf(clause, root);
    const chosen = c.if ? (matches(c.if, value, root) ? c.then : c.else) : c;
    if (chosen) { const { allOf: _all, ...resolved } = branchOf(chosen, value, root); base = merge(base, resolved); }
  }
  if (base.if) {
    const chosen = matches(base.if, value, root) ? base.then : base.else;
    if (chosen) base = merge(base, branchOf(chosen, value, root));
  }
  return base;
}
export function initialVariant(schema: Schema, index: number, root: Schema): Json {
  const base = schemaOf(schema, root), { oneOf: _one, anyOf: _any, ...common } = base;
  return initial(merge(common, variantsOf(base)?.[index] ?? {}), root);
}
export function initial(schema: Schema, root: Schema, depth = 0): Json {
  const base = schemaOf(schema, root);
  if (depth > 32) return null;
  if (base.default !== undefined) return structuredClone(base.default);
  if (base.const !== undefined) return structuredClone(base.const);
  if (base.enum) return structuredClone(base.enum[0] ?? "");
  const variants = variantsOf(base);
  if (variants) { const { oneOf: _one, anyOf: _any, ...common } = base; return initial(merge(common, variants[0] ?? {}), root, depth + 1); }
  if (base.type === "object" || !base.type && base.properties) {
    const seed = Object.fromEntries((base.required ?? []).map((key) => [key, initial(base.properties?.[key] ?? {}, root, depth + 1)]));
    const active = branchOf(schema, seed, root);
    return Object.fromEntries((active.required ?? []).map((key) => [key, initial(active.properties?.[key] ?? {}, root, depth + 1)]));
  }
  if (base.type === "array") return Array.from({ length: Math.min(base.minItems ?? 0, 100) }, () => initial(base.items ?? {}, root, depth + 1));
  return base.type === "boolean" ? false : base.type === "number" || base.type === "integer" ? base.minimum ?? 0 : base.type === "null" ? null : "";
}
export function childSchema(schema: Schema, key: string): Schema {
  if (schema.properties?.[key]) return schema.properties[key] ?? {};
  for (const [pattern, child] of Object.entries(schema.patternProperties ?? {})) if (new RegExp(pattern).test(key)) return child;
  return typeof schema.additionalProperties === "object" ? schema.additionalProperties : {};
}
