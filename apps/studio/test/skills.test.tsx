import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SkillEditor } from "../src/SkillEditor.js";
import { command } from "../src/transport.js";
import { StudioError } from "../src/model.js";
vi.mock("../src/transport.js", () => ({ command: vi.fn() }));
const text = "---\nname: example\n---\n## Procedure\nCheck the work.\n";
const report = { ok: true, findings: [], schema: { type: "object", required: ["name"], properties: { name: { type: "string" } } }, frontmatter: { name: "example" }, body: "## Procedure\nCheck the work.", sections: ["Procedure"], role_slices: { checker: "Check the work." }, eval_cases: 3, eval_minimum: 5, current_evals_green: false };
let conflict = false;
beforeEach(() => {
  conflict = false;
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.mocked(command).mockImplementation(async (r) => {
    if (r.op === "skill_open") return { name: "example", text, revision: "one", report };
    if (r.op === "skill_check") return report;
    if (r.op === "skill_save") { if (conflict) throw new StudioError("conflict", "Changed on disk"); return { name: "example", text: r.text, revision: "two", report }; }
    return { ok: false, problems: ["Current local-model evaluation required"] };
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });
async function open(onClose = vi.fn()) {
  render(<SkillEditor skills={[{ name: "example", kind: "agent", path: "skills/agent/example/SKILL.md" }]} author="lead" registerGuard={() => undefined} onClose={onClose} />);
  fireEvent.change(screen.getByLabelText("Skill"), { target: { value: "example" } });
  await screen.findByLabelText("Complete skill source");
}
test("skill submission uses the saved revision and exposes current-version evaluation blockers", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("Complete skill source"), { target: { value: text + "A correction.\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Save skill draft" }));
  await screen.findByText("Saved on this computer");
  fireEvent.click(screen.getByRole("button", { name: "Submit skill through gates" }));
  await screen.findByRole("alert");
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "skill_submit", revision: "two" }));
});
test("a conflicting skill draft blocks closing and offers a copy", async () => {
  const onClose = vi.fn(); await open(onClose);
  conflict = true;
  fireEvent.change(screen.getByLabelText("Complete skill source"), { target: { value: text + "Retain this correction.\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Close skill editor" }));
  await screen.findByText("Changed on disk");
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Download retained skill draft" })).toBeTruthy();
});
