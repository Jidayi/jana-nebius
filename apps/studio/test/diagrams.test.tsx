import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DiagramEditor } from "../src/DiagramEditor.js";
import { command } from "../src/transport.js";
vi.mock("../src/transport.js", () => ({ command: vi.fn() }));
const id = "dgm.phy.fixture.v1", svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle data-part="ball" cx="50" cy="50" r="10"/></svg>';
const entry = { id, title: "Fictional ball", parts: [{ id: "ball", name: "Ball", function: "A ball" }], licence: "LicenseRef-Own", review: {} };
const report = { ok: true, problems: [], schema: { type: "object", properties: { id: { type: "string" }, title: { type: "string" } } } };
beforeEach(() => {
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.mocked(command).mockImplementation(async (r) => {
    if (r.op === "diagram_open") return { entry, svg, revision: "one", svg_revision: "svg-one", report };
    if (r.op === "diagram_check") return report;
    if (r.op === "diagram_sanitise") return { svg, removed: ["element script"], ok: true };
    if (r.op === "diagram_save") return { entry: r.entry, svg: r.svg, revision: "two", svg_revision: "svg-two", report };
    return { svg };
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });
async function open() {
  render(<DiagramEditor pack="pack.phy.o" diagrams={[{ id, title: "Fictional ball" }]} author="lead" registerGuard={() => undefined} onClose={() => undefined} />);
  fireEvent.change(screen.getByLabelText("Diagram"), { target: { value: id } });
  await screen.findByLabelText("SVG source");
}
test("unsafe SVG stays source text and sanitisation reports removals before saving", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("SVG source"), { target: { value: svg.replace("</svg>", "<script>alert(1)</script></svg>") } });
  expect(document.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Sanitise drawing and show removals" }));
  await screen.findByText("Removed: element script");
  expect((screen.getByLabelText("SVG source") as HTMLTextAreaElement).value).toBe(svg);
  fireEvent.click(screen.getByRole("button", { name: "Save diagram draft" }));
  await screen.findByText("Saved on this computer");
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "diagram_save", svg_revision: "svg-one", revision: "one" }));
});
test("keyboard element selection uses the same tagging operation as the drawing", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("Drawing element"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Assign part"), { target: { value: "ball" } });
  fireEvent.click(screen.getByRole("button", { name: "Tag selected element" }));
  await screen.findByText("Part tag updated");
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "diagram_tag", element: 1, part: "ball" }));
});

test("sanitisation reads the latest draft when edits and the action share a render batch", async () => {
  await open();
  const unsafe = svg.replace("</svg>", "<script>alert(1)</script></svg>");
  act(() => {
    fireEvent.change(screen.getByLabelText("SVG source"), { target: { value: unsafe } });
    fireEvent.click(screen.getByRole("button", { name: "Sanitise drawing and show removals" }));
  });
  await screen.findByText("Removed: element script");
  expect(command).toHaveBeenCalledWith(expect.objectContaining({ op: "diagram_sanitise", svg: unsafe }));
  expect((screen.getByLabelText("SVG source") as HTMLTextAreaElement).value).toBe(svg);
  expect(document.querySelector("script")).toBeNull();
});

test("a sanitisation result never overwrites SVG edited while the action is pending", async () => {
  await open();
  let finish: ((value: { svg: string; removed: string[] }) => void) | undefined;
  vi.mocked(command).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "Sanitise drawing and show removals" }));
  const newer = svg.replace('r="10"', 'r="12"');
  fireEvent.change(screen.getByLabelText("SVG source"), { target: { value: newer } });
  await act(async () => { finish?.({ svg, removed: [] }); });
  await screen.findByText("The drawing changed during this action; run it again.");
  expect((screen.getByLabelText("SVG source") as HTMLTextAreaElement).value).toBe(newer);
  expect(screen.queryByText("Removed: nothing unsafe")).toBeNull();
});
