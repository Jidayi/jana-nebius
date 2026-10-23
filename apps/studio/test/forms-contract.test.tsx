import React, { useState } from "react";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ContractForm } from "../src/Form.js";
import { branchOf, initial, initialVariant, schemaOf, type Json, type Schema } from "../src/model.js";
const repository = resolve(process.cwd(), process.cwd().endsWith("/apps/studio") ? "../.." : ".");
const bundles = JSON.parse(execFileSync(process.env.JANA_PYTHON ?? resolve(repository, ".venv/bin/python"), ["-c", `import json
from pack_builder.form_schema import form_schema
print(json.dumps({name:form_schema(name) for name in ['content/content-pack','skills/skill-frontmatter','visuals/diagram-entry','visuals/visual-spec']}))`], { cwd: repository, encoding: "utf8" })) as Record<string, Schema>;
afterEach(cleanup);
function Harness({ schema, root = schema, value, identityEditable = true }: { schema: Schema; root?: Schema; value: Json; identityEditable?: boolean }) {
  const [data, setData] = useState(value);
  return <><ContractForm schema={schema} root={root} value={data} onChange={setData} records={[]} identityEditable={identityEditable} /><pre data-testid="value">{JSON.stringify(data)}</pre></>;
}
const value = () => JSON.parse(screen.getByTestId("value").textContent ?? "null") as Json;
it("aut07_forms_cover_contract: every bundled canonical field resolves and has a typed form control", () => {
  let fields = 0, leaves = 0, refs = 0;
  for (const [name, root] of Object.entries(bundles)) {
    const visited = new Set<Schema>();
    const walk = (node: Schema, path: string) => {
      if (visited.has(node)) return; visited.add(node);
      if (node.$ref) { expect(node.$ref, `${name}:${path}`).toMatch(/^#\/\$defs\//); const resolved = schemaOf(node, root); expect(resolved.$ref).toBeUndefined(); refs++; }
      for (const [key, child] of Object.entries(node.properties ?? {})) {
        fields++;
        const resolved = schemaOf(child, root);
        const variants = resolved.oneOf ?? resolved.anyOf ?? (Array.isArray(resolved.type) ? resolved.type.map((type) => ({ ...resolved, type })) : [resolved]);
        for (const variant of variants) {
          const s = schemaOf(variant, root), type = s.type;
          // Container behavior is exercised separately; scalar leaves use their actual canonical schema.
          if (type === "object" || type === "array" || s.properties || s.oneOf || s.anyOf || s.allOf) continue;
          const before = initial(s, root);
          if (before !== null && typeof before === "object") continue;
          const view = render(<Harness schema={s} root={root} value={before} />);
          const control = screen.getByLabelText("$") as HTMLInputElement;
          expect(control, `${name}:${path}.${key}`).toBeTruthy();
          if (s.enum && s.enum.length > 1) {
            fireEvent.change(control, { target: { value: JSON.stringify(s.enum[1]) } }); expect(value()).toEqual(s.enum[1]);
            fireEvent.change(control, { target: { value: JSON.stringify(before) } });
          } else if (s.const === undefined && !s.enum && type !== "null") {
            if (type === "boolean") { fireEvent.click(control); expect(value()).toBe(!before); fireEvent.click(control); }
            else { const next = type === "integer" || type === "number" ? 37 : "Edited Ω value"; fireEvent.change(control, { target: { value: String(next) } }); expect(value()).toEqual(next); fireEvent.change(control, { target: { value: String(before ?? "") } }); }
          }
          expect(value()).toEqual(before); leaves++; view.unmount();
        }
        walk(child, `${path}.${key}`);
      }
      for (const child of Object.values(node.$defs ?? {})) walk(child, `${path}.$defs`);
      for (const child of Object.values(node.patternProperties ?? {})) walk(child, `${path}.*`);
      if (typeof node.additionalProperties === "object") walk(node.additionalProperties, `${path}.*`);
      if (node.items) walk(node.items, `${path}[]`);
      for (const child of [...node.oneOf ?? [], ...node.anyOf ?? [], ...node.allOf ?? [], ...[node.if, node.then, node.else].filter((s): s is Schema => !!s)]) walk(child, path);
    };
    walk(root, "$ ");
  }
  expect(fields).toBeGreaterThan(800); expect(leaves).toBeGreaterThan(500); expect(refs).toBeGreaterThan(200);
  console.info(`AUT-07 canonical inventory: ${fields} fields, ${leaves} scalar branch round-trips, ${refs} local references`);
});
it("handles nullable objects, conditional branches, typed maps, arbitrary JSON and deep fields without loss", () => {
  const nullable: Schema = { type: ["object", "null"], properties: { text: { type: "string" } }, required: ["text"] };
  render(<Harness schema={nullable} value={null} />); expect(screen.getByLabelText("$").textContent).toBe("null");
  fireEvent.change(screen.getByLabelText("$ variant"), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText("$.text"), { target: { value: "kept" } }); expect(value()).toEqual({ text: "kept" });
  fireEvent.change(screen.getByLabelText("$ variant"), { target: { value: "1" } }); expect(value()).toBeNull(); cleanup();
  const conditional: Schema = { type: "object", properties: { kind: { enum: ["a", "b"] } }, required: ["kind"], allOf: [{ if: { properties: { kind: { const: "b" } }, required: ["kind"] }, then: { properties: { detail: { type: "number" } }, required: ["detail"] } }] };
  render(<Harness schema={conditional} value={{ kind: "a" }} />); expect(screen.queryByLabelText("$.detail")).toBeNull();
  fireEvent.change(screen.getByLabelText("$.kind"), { target: { value: '"b"' } }); fireEvent.change(screen.getByLabelText("$.detail"), { target: { value: "12" } }); expect(value()).toEqual({ kind: "b", detail: 12 }); cleanup();
  render(<Harness schema={{ type: "object", additionalProperties: { type: "number" } }} value={{ first: 0 }} />);
  fireEvent.change(screen.getByLabelText("New key in $"), { target: { value: "second" } }); fireEvent.click(screen.getByText("Add key")); expect(value()).toEqual({ first: 0, second: 0 });
  fireEvent.change(screen.getByLabelText("$.second"), { target: { value: "7" } }); expect(value()).toEqual({ first: 0, second: 7 }); cleanup();
  render(<Harness schema={{ type: "object", additionalProperties: true }} value={{ flag: false, count: 0 }} />);
  fireEvent.change(screen.getByLabelText("$.flag type"), { target: { value: "null" } }); expect(value()).toEqual({ flag: null, count: 0 }); cleanup();
  let schema: Schema = { type: "string" }, data: Json = "deep";
  for (let i = 0; i < 16; i++) { schema = { type: "object", properties: { nested: schema }, required: ["nested"], additionalProperties: false }; data = { nested: data }; }
  render(<Harness schema={schema} value={data} />); const path = "$" + ".nested".repeat(16);
  fireEvent.change(screen.getByLabelText(path), { target: { value: "changed" } }); fireEvent.change(screen.getByLabelText(path), { target: { value: "deep" } }); expect(value()).toEqual(data);
});
it("keeps common branch fields, array ordering and immutable identities under their owned controls", () => {
  const union: Schema = { type: "object", properties: { shared: { type: "string" } }, required: ["shared"], oneOf: [{ properties: { kind: { const: "a" } }, required: ["kind"] }, { properties: { kind: { const: "b" }, answer: { type: "number" } }, required: ["kind", "answer"] }] };
  expect(initialVariant(union, 1, union)).toEqual({ shared: "", kind: "b", answer: 0 });
  expect(branchOf(union, { shared: "", kind: "b", answer: 5 }, union).properties).toHaveProperty("answer");
  render(<Harness schema={{ type: "array", items: { type: "number" }, maxItems: 2 }} value={[0, 2]} />);
  expect((screen.getByText("Add $") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText("Move $[1] up")); expect(value()).toEqual([2, 0]); fireEvent.click(screen.getByLabelText("Move $[0] down")); expect(value()).toEqual([0, 2]); cleanup();
  render(<Harness identityEditable={false} schema={{ type: "object", properties: { id: { type: "string" }, nested: { type: "object", properties: { id: { type: "string" } } } } }} value={{ id: "immutable", nested: { id: "editable" } }} />);
  expect(screen.queryByLabelText("$.id")).toBeNull(); expect(screen.getByText("immutable")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("$.nested.id"), { target: { value: "changed" } }); expect(value()).toEqual({ id: "immutable", nested: { id: "changed" } });
});
