import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReferenceEditor } from "../src/ReferenceEditor.js";
import { command } from "../src/transport.js";
import { StudioError } from "../src/model.js";
vi.mock("../src/transport.js", () => ({ command: vi.fn() }));
const reference = { rows: [{ key: "gravity", value: "9.8" }], path: "ref/conventions.yaml", revision: "one", report: { ok: true, problems: [] }, schema: { $defs: { Convention: { type: "object", properties: { key: { type: "string" }, value: { type: "string" } }, required: ["key", "value"], additionalProperties: false } } } };
beforeEach(() => {
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.mocked(command).mockImplementation(async (r) => ({ ...reference, rows: r.rows ?? reference.rows, revision: r.op === "reference_save" ? "two" : "one" }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });
it("saves typed convention fields and waits for persistence before closing", async () => {
  const close = vi.fn(); let guard = async () => true;
  render(<ReferenceEditor pack="pack.phy.o" author="lead" registerGuard={(next) => { guard = next; }} onClose={close} />);
  fireEvent.change(await screen.findByLabelText("$.conventions[0].value"), { target: { value: "10" } });
  expect(await guard()).toBe(true);
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "reference_save", revision: "one", rows: [{ key: "gravity", value: "10" }] }));
  fireEvent.click(screen.getByText("Close")); await waitFor(() => expect(close).toHaveBeenCalledOnce());
});
it("retains a conflicting convention draft and blocks modal and native navigation", async () => {
  const close = vi.fn(); let guard = async () => true;
  vi.mocked(command).mockImplementation(async (r) => { if (r.op === "reference_save") throw new StudioError("conflict", "Changed on disk"); return reference; });
  render(<ReferenceEditor pack="pack.phy.o" author="lead" registerGuard={(next) => { guard = next; }} onClose={close} />);
  fireEvent.change(await screen.findByLabelText("$.conventions[0].value"), { target: { value: "retained" } });
  expect(await guard()).toBe(false); fireEvent.click(screen.getByText("Close"));
  await screen.findByRole("alert"); expect(close).not.toHaveBeenCalled();
  expect((screen.getByLabelText("$.conventions[0].value") as HTMLTextAreaElement).value).toBe("retained");
  const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event); expect(event.defaultPrevented).toBe(true);
});
