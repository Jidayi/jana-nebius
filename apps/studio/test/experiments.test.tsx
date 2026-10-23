import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Experiments } from "../src/Experiments.js";
import { command } from "../src/transport.js";
vi.mock("../src/transport.js", () => ({ command: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
test("signature bench exposes collisions and opens their actual source item", async () => {
  vi.mocked(command).mockResolvedValue({ ok: true, items: [], collisions: [{ item_id: "itm.phy.o.motion.0001", part: "a", misconceptions: ["mc.a", "mc.b"], wrong_answer: "0.125" }] });
  const onOpen = vi.fn();
  render(<Experiments pack="pack.phy.o" table="misconceptions" record={{ id: "mc.a" }} onOpen={onOpen} />);
  fireEvent.click(screen.getByRole("button", { name: "Run signature bench" }));
  fireEvent.click(await screen.findByRole("button", { name: "itm.phy.o.motion.0001" }));
  expect(onOpen).toHaveBeenCalledWith("itm.phy.o.motion.0001");
  expect(command).toHaveBeenCalledWith({ op: "signature_bench", pack: "pack.phy.o", record: { id: "mc.a" } });
});
test("sampler failures are visible and changing the draft clears stale results", async () => {
  vi.mocked(command).mockResolvedValue({ ok: false, problems: ["Invalid parameter range"], variants: [] });
  const props = { pack: "pack.phy.o", table: "item_templates", record: { id: "tmpl.a" }, onOpen: vi.fn() };
  const view = render(<Experiments {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Generate 50 samples" }));
  await screen.findByText("Invalid parameter range");
  view.rerender(<Experiments {...props} record={{ id: "tmpl.a", version: "0.2.0" }} />);
  expect(screen.queryByText("Invalid parameter range")).toBeNull();
});

test("publication failure is visible and an unsaved draft prevents issuing a request", async () => {
  const { Workflow } = await import("../src/Workflow.js");
  vi.mocked(command).mockImplementation(async (request) => request.op === "workflow" ? { comments: [] } : { ok: false, problems: ["Run green evaluations on the current content before publishing"] });
  const beforeSave = vi.fn().mockResolvedValue(false);
  render(<Workflow pack="pack.phy.o" table="items" record={{ id: "itm.a" }} author="lead" beforeSave={beforeSave} preview={() => null} />);
  fireEvent.click(screen.getByRole("button", { name: "Queue publication" }));
  await vi.waitFor(() => expect(beforeSave).toHaveBeenCalledOnce());
  expect(vi.mocked(command).mock.calls.some(([r]) => r.op === "publish")).toBe(false);
  await vi.waitFor(() => expect((screen.getByRole("button", { name: "Queue publication" }) as HTMLButtonElement).disabled).toBe(false));
  beforeSave.mockResolvedValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Queue publication" }));
  await screen.findByText("Run green evaluations on the current content before publishing");
});

test("retirement requires a successful impact preview before applying and refreshes the library", async () => {
  const { Changes } = await import("../src/Changes.js");
  vi.mocked(command).mockImplementation(async (r) => r.apply ? { ok: true, retired: "itm.a" } : { ok: true, record_revision: "record-one", manifest_revision: "manifest-one", impact: { records: [], skills: [] } });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  render(<Changes pack="pack.phy.o" table="items" record={{ id: "itm.a" }} author="lead" records={[]} beforeSave={async () => true} onChanged={onChanged} />);
  expect(screen.queryByRole("button", { name: "Apply retirement" })).toBeNull();
  fireEvent.click(screen.getByText("Retire this record"));
  fireEvent.change(screen.getByLabelText("Retirement reason"), { target: { value: "Incorrect key." } });
  fireEvent.click(screen.getByRole("button", { name: "Preview retirement impact" }));
  fireEvent.click(await screen.findByRole("button", { name: "Apply retirement" }));
  await vi.waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "retire", apply: true, record_revision: "record-one", reason: "Incorrect key." }));
});

test("bulk import needs a clean dry run and carries its exact digest into application", async () => {
  const { BulkImport } = await import("../src/BulkImport.js");
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.mocked(command).mockImplementation(async (r) => r.op === "import_preview" ? { ok: true, preview_sha256: "current-source-digest", records: [{ id: "itm.a" }], problems: [] } : { ok: true, imported: ["itm.a"] });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  render(<BulkImport pack="pack.phy.o" author="lead" registerGuard={() => undefined} onChanged={onChanged} onClose={() => undefined} />);
  expect(screen.queryByRole("button", { name: "Import verified dry run as drafts" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Import source"), { target: { value: "- external_ref: synthetic\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Run import dry run" }));
  fireEvent.click(await screen.findByRole("button", { name: "Import verified dry run as drafts" }));
  await vi.waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "import_apply", preview_sha256: "current-source-digest" }));
});

test("simulation requests default to five runs and show explicit missing-runtime requirements", async () => {
  const { EvaluationJobs } = await import("../src/EvaluationJobs.js");
  vi.mocked(command).mockImplementation(async (r) => {
    if (r.op === "job_personas") return { personas: ["answer_seeker"] };
    if (r.op === "workflow") return { jobs: [] };
    return { ok: true, message: "Simulated students need the evaluation service. Your request is queued." };
  });
  render(<EvaluationJobs pack="pack.phy.o" table="items" id="itm.a" author="lead" beforeSave={async () => true} />);
  fireEvent.click(screen.getByText("Simulated students"));
  await screen.findByLabelText("answer seeker");
  fireEvent.click(screen.getByRole("button", { name: "Queue simulated students" }));
  await screen.findByText("Simulated students need the evaluation service. Your request is queued.");
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ kind: "simulation", count: 5, personas: ["answer_seeker"] }));
});

test("worked-example fading uses only existing steps and a variant carries its authored recipe", async () => {
  const { ExampleTools } = await import("../src/ExampleTools.js");
  const onChange = vi.fn(), onCreated = vi.fn();
  const record = { id: "wex.phy.o.motion.0001", steps: [{ n: 1 }, { n: 2 }], fading_order: [2, 1] };
  vi.mocked(command).mockResolvedValue({ ok: true, opened: { record: { id: "wex.phy.o.motion.0002" } } });
  render(<ExampleTools pack="pack.phy.o" record={record} records={[{ id: "itpl.phy.o.motion.0001", table: "item_templates", title: "Speed", node_id: null, code: null }]} author="lead" registerGuard={() => undefined} beforeSave={async () => true} onChange={onChange} onCreated={onCreated} />);
  fireEvent.click(screen.getByRole("button", { name: "Move step 1 earlier" }));
  expect(onChange).toHaveBeenCalledWith({ ...record, fading_order: [1, 2] });
  expect(screen.getByLabelText("Add fading step").querySelectorAll("option")).toHaveLength(1);
  fireEvent.click(screen.getByText("Create a variant from a template"));
  fireEvent.change(screen.getByLabelText("Variant template"), { target: { value: "itpl.phy.o.motion.0001" } });
  fireEvent.change(screen.getByLabelText("New worked example id"), { target: { value: "wex.phy.o.motion.0002" } });
  fireEvent.change(screen.getByLabelText("Authored variant recipe"), { target: { value: '{"steps":[]}' } });
  fireEvent.click(screen.getByRole("button", { name: "Verify and create variant draft" }));
  await vi.waitFor(() => expect(onCreated).toHaveBeenCalledOnce());
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "template_variant", recipe: { steps: [] }, sample: 0 }));
});
