import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../src/App.js";
import { StudioError, type Opened, type Workspace } from "../src/model.js";
import { command, openWorkspace } from "../src/transport.js";
vi.mock("../src/transport.js", () => ({ command: vi.fn(), openWorkspace: vi.fn(), exitStudio: vi.fn() }));
const record = { id: "kc.phy.o.motion.speed", title: "Speed", prerequisites: [] };
const opened: Opened = { pack: "pack.phy.o", table: "kcs", path: "speed.yaml", revision: "one", record };
const workspace: Workspace = { root: "/synthetic/curriculum", packs: [{ id: "pack.phy.o", subject: "phy", level: "o",
  records: [{ ...record, table: "kcs", node_id: null, code: null }] }], tables: ["kcs"],
  schema: { $defs: { kc: { type: "object", required: ["id", "title"], properties: {
    id: { type: "string" }, title: { type: "string" }, prerequisites: { type: "array", items: { type: "string" } } } } } },
  definitions: { kcs: "kc" }, accounts: [{ id: "lead", name: "Synthetic author", roles: ["curriculum_lead"] }], author: "lead" };
let conflicting = false, failedOpen = false;
beforeEach(() => {
  conflicting = failedOpen = false;
  vi.mocked(openWorkspace).mockResolvedValue(workspace);
  vi.mocked(command).mockImplementation(async (request) => {
    if (request.op === "open") { if (failedOpen) throw new Error("Synthetic read failure"); return structuredClone(opened); }
    if (request.op === "validate") return { ok: false, problems: ["Prerequisite cycle: speed → speed"] };
    if (request.op === "graph") return { nodes: [record] };
    if (request.op === "references") return { records: [], skills: [] };
    if (request.op === "save") {
      if (conflicting) throw new StudioError("conflict", "Changed on disk");
      return { ...opened, record: request.record, revision: "two" };
    }
    return { ok: true, problems: [], checks: [] };
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
async function open() {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Open local workspace" }));
  fireEvent.click(await screen.findByRole("button", { name: /Speed/ }));
  await screen.findByRole("heading", { name: "Speed" });
}

test("shows live validator cycle failures and the prerequisite navigation without a model", async () => {
  await open();
  await screen.findByText("Prerequisite cycle: speed → speed");
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "validate", table: "kcs", record }));
  expect(screen.getByText(/Prerequisite graph/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "verify" }));
  await screen.findByRole("heading", { name: "CLI pipeline result" });
  expect(command).toHaveBeenCalledWith({ op: "check", category: "verify", pack: "pack.phy.o" });
});

test("failed conflict reload keeps the edited draft until a replacement has loaded", async () => {
  await open();
  fireEvent.change(screen.getByRole("textbox", { name: "$.title" }), { target: { value: "Retained edited title" } });
  conflicting = true;
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByText("Changed on disk");
  fireEvent.click(screen.getByRole("button", { name: "Reload disk version" }));
  let dialog = screen.getByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Keep my draft" }));
  expect(screen.getByRole("textbox", { name: "$.title" }).getAttribute("value") ??
    (screen.getByRole("textbox", { name: "$.title" }) as HTMLTextAreaElement).value).toBe("Retained edited title");
  failedOpen = true;
  fireEvent.click(screen.getByRole("button", { name: "Reload disk version" }));
  dialog = screen.getByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Reload disk version" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect((screen.getByRole("textbox", { name: "$.title" }) as HTMLTextAreaElement).value).toBe("Retained edited title");
  expect(screen.getByText("Conflict · draft retained")).toBeTruthy();
});

test("invalid JSON blocks workspace switching and remains editable", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "JSON source" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Record JSON" }), { target: { value: '{"unfinished":' } });
  fireEvent.click(screen.getByRole("button", { name: "Open another workspace" }));
  await screen.findByText("Finish the JSON object before saving.");
  expect(openWorkspace).toHaveBeenCalledOnce();
  expect((screen.getByRole("textbox", { name: "Record JSON" }) as HTMLTextAreaElement).value).toBe('{"unfinished":');
});
