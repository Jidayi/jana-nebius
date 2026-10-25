import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { citationKey, StudyCitation, StudyCitations } from "../src/learn/StudyCitation.js";

afterEach(cleanup);
const citation = { source_id: `src_${"0".repeat(26)}`, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" };
test("one page badge retains every supporting passage and restores trigger focus", () => {
  const onOpen = vi.fn(), second = { ...citation, start: 4, end: 7, quote: "RNA" };
  render(<StudyCitations citations={[citation, second]} locate={() => ({ kind: "page", page: 4 })} title={() => "notes.pdf"} onOpen={onOpen} />);
  const badge = screen.getByRole("button", { name: "notes.pdf · Page 4 · 2 supporting passages" });
  expect(screen.getAllByText("p. 4")).toHaveLength(1);
  fireEvent.click(badge);
  expect(screen.getByRole("menu", { name: /2 supporting passages/ })).toBeTruthy();
  expect(screen.getByText("DNA")).toBeTruthy();
  expect(screen.getByText("RNA")).toBeTruthy();
  fireEvent.click(screen.getByRole("menuitem", { name: /Passage 2/ }));
  expect(onOpen).toHaveBeenLastCalledWith(second);
  expect(document.activeElement).toBe(badge);
  fireEvent.click(badge);
  fireEvent.click(screen.getByRole("menuitem", { name: /Passage 1/ }));
  expect(onOpen).toHaveBeenLastCalledWith(citation);
});
test("grouping is per point, file and revision, and keeps different pages separate", () => {
  const otherFile = { ...citation, source_id: `src_${"1".repeat(26)}` }, replacement = { ...citation, revision: 2 }, nextPage = { ...citation, chunk_id: `sck_${"1".repeat(26)}` };
  const refs = [citation, { ...citation, start: 4 }, otherFile, replacement, nextPage];
  const locate = (ref: typeof citation) => ({ kind: "page" as const, page: ref === nextPage ? 5 : 4 });
  render(<><StudyCitations citations={refs} locate={locate} title={() => "notes.pdf"} onOpen={vi.fn()} />
    <StudyCitations citations={[citation]} locate={locate} title={() => "notes.pdf"} onOpen={vi.fn()} /></>);
  expect(screen.getAllByText("p. 4")).toHaveLength(4);
  expect(screen.getAllByText("p. 5")).toHaveLength(1);
});
test("legacy formula previews link to the original evidence rather than presenting broken math", () => {
  const onOpen = vi.fn(), formula = { ...citation, quote: "Φ = \uf8eb matrix \uf8f6" };
  render(<StudyCitations citations={[formula, citation]} locate={() => ({ kind: "page", page: 13 })} title={() => "notes.pdf"} onOpen={onOpen} />);
  fireEvent.click(screen.getByRole("button", { name: /2 supporting passages/ }));
  expect(screen.getByText("Contains a formula. Open the original page for exact notation.")).toBeTruthy();
  fireEvent.click(screen.getByRole("menuitem", { name: /Passage 1/ }));
  expect(onOpen).toHaveBeenCalledWith(formula);
});
test("keyboard navigation reaches every passage in a larger group and Escape restores the badge", () => {
  const refs = Array.from({ length: 4 }, (_, i) => ({ ...citation, start: i * 4, end: i * 4 + 3, quote: `Quote ${i + 1}` }));
  const onOpen = vi.fn();
  render(<StudyCitations citations={refs} locate={() => ({ kind: "page", page: 13 })} title={() => "notes.pdf"} onOpen={onOpen} />);
  const badge = screen.getByRole("button", { name: /4 supporting passages/ });
  fireEvent.click(badge);
  const menu = screen.getByRole("menu");
  expect(screen.getAllByRole("menuitem")).toHaveLength(4);
  fireEvent.keyDown(menu, { key: "End" });
  expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: /Passage 4/ }));
  fireEvent.click(document.activeElement!);
  expect(onOpen).toHaveBeenCalledWith(refs[3]);
  fireEvent.click(badge);
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(badge);
});
test("unknown page locations never collapse and a disabled group cannot open", () => {
  const { rerender } = render(<StudyCitations citations={[citation, citation]} locate={() => undefined} title={() => undefined} onOpen={vi.fn()} />);
  expect(screen.getAllByRole("button")).toHaveLength(2);
  rerender(<StudyCitations citations={[citation, citation]} locate={() => ({ kind: "page", page: 4 })} title={() => undefined} disabled onOpen={vi.fn()} />);
  fireEvent.click(screen.getByRole("button"));
  expect(screen.queryByRole("menu")).toBeNull();
});
test("page badges expose the filename and preserve the exact verified reference", () => {
  const onOpen = vi.fn();
  render(<StudyCitation citation={citation} locator={{ kind: "page", page: 65 }} sourceTitle="notes.pdf" number={1} onOpen={onOpen} />);
  const button = screen.getByRole("button", { name: "notes.pdf · Page 65" });
  expect(button.textContent).toBe("p. 65");
  expect(document.getElementById(button.getAttribute("aria-describedby")!)?.textContent).toBe("notes.pdf · Page 65");
  fireEvent.click(button);
  expect(onOpen).toHaveBeenCalledWith(citation);
});
test.each([[155000, "02:35"], [3725000, "1:02:05"]])("timestamp %i is readable and keyboard operable", (start_ms, label) => {
  const onOpen = vi.fn();
  render(<StudyCitation citation={citation} locator={{ kind: "time", start_ms, end_ms: start_ms + 1000 }} sourceTitle="Lecture" number={1} onOpen={onOpen} />);
  const button = screen.getByRole("button", { name: `Lecture · At ${label}` });
  expect(button.textContent).toBe(label);
  expect(button.tagName).toBe("BUTTON");
  expect(button.getAttribute("tabindex")).not.toBe("-1");
  fireEvent.click(button);
  expect(onOpen).toHaveBeenCalledWith(citation);
});
test("unknown locations stay numbered and replacement revisions remain identifiable", () => {
  render(<StudyCitation citation={{ ...citation, revision: 2 }} sourceTitle="notes.pdf" number={3} onOpen={vi.fn()} />);
  const button = screen.getByRole("button", { name: /notes.pdf · Reference 3 · .*2/ });
  expect(button.textContent).toBe("[3]");
  expect(screen.queryByText(/Source \d/)).toBeNull();
  expect(citationKey(citation)).not.toBe(citationKey({ ...citation, revision: 2 }));
  expect(citationKey(citation)).not.toBe(citationKey({ ...citation, source_id: `src_${"1".repeat(26)}` }));
});
