import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Analytics } from "../src/Analytics.js";
import { command } from "../src/transport.js";
vi.mock("../src/transport.js", () => ({ command: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

// Synthetic analytics: invented records, counts and notes.
const shown = { record_id: "itm.phy.o.motion.0001", students: 260, responses: 260, suppressed: false, facility: { value: 0.98, interval: [0.95, 0.99] }, discrimination: null, distractors: {} };
const few = { record_id: "itm.phy.o.motion.0002", students: 9, responses: 9, suppressed: true, facility: null, discrimination: null, distractors: null };
const opened = { pack: "pack.phy.o", table: "items", path: "x", revision: "r", record: { id: "itm.phy.o.motion.0001" } };
function answer(request: Record<string, unknown>) {
  if (request.op === "analytics_queue") return { entries: [{ record_id: "itm.phy.o.motion.0001", status: "open", reasons: ["facility_high"], statistics: shown, calibration: { replaced: true, difficulty: -4, prior: -0.8 } }] };
  if (request.op === "inbox_list") return { rows: [{ record_id: "itm.phy.o.motion.0001", counts: { wrong_answer: 3 }, notes: [{ note: "The key looks wrong" }] }] };
  if (request.op === "analytics_records") return { records: [shown, few] };
  if (request.op === "inbox_open") return opened;
  return { status: "dismissed" };
}

test("test_aut37_studio_shows_figures_with_intervals_and_withholds_small_samples", async () => {
  vi.mocked(command).mockImplementation(async (r) => answer(r));
  render(<Analytics pack="pack.phy.o" author="lead" onOpen={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Refresh analytics" }));
  expect(await screen.findByText("Review queue · 1 open")).toBeTruthy();
  expect(screen.getAllByText("Facility: 0.980 (95% 0.950 to 0.990)").length).toBeGreaterThan(0);
  expect(screen.getByText("Too few students to show figures.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "No problem" }));
  await vi.waitFor(() => expect(command).toHaveBeenCalledWith({ op: "analytics_resolve", id: "itm.phy.o.motion.0001", outcome: "dismissed", author: "lead" }));
});

test("test_aut38_studio_report_opens_a_draft_change", async () => {
  vi.mocked(command).mockImplementation(async (r) => answer(r));
  const onOpen = vi.fn().mockResolvedValue(undefined);
  render(<Analytics pack="pack.phy.o" author="lead" onOpen={onOpen} />);
  fireEvent.click(screen.getByRole("button", { name: "Refresh analytics" }));
  expect(await screen.findByText("The key looks wrong")).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: "Open draft change on itm.phy.o.motion.0001" })[1] as HTMLElement);
  await vi.waitFor(() => expect(onOpen).toHaveBeenCalledWith(opened));
  expect(command).toHaveBeenCalledWith({ op: "inbox_open", pack: "pack.phy.o", table: "items", id: "itm.phy.o.motion.0001", author: "lead" });
});

test("test_aut37_studio_analytics_need_an_author", () => {
  render(<Analytics pack="pack.phy.o" author={null} onOpen={vi.fn()} />);
  expect((screen.getByRole("button", { name: "Refresh analytics" }) as HTMLButtonElement).disabled).toBe(true);
});
