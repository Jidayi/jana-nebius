import { act, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Fixture, id, SESSION } from "./harness.js";
import { TutorAnnouncements } from "../src/transcript/Announcements.js";
import { TurnView } from "../src/transcript/Turn.js";
import { Board } from "../src/board/Board.js";

afterEach(() => { cleanup(); vi.useRealTimers(); });
test.each(["light", "dark"])("loc14_no_delta_announcements: %s", async (theme) => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-18T12:00:00Z"));
  const f = new Fixture(), turn = f.startTurn();
  const { container } = f.render(<div data-theme={theme}><TutorAnnouncements sessionId={SESSION} /><TurnView turnId={turn} /><Board sessionId={SESSION} /></div>);
  const live = container.querySelector("[data-tutor-announcements]")!;
  const messages: string[] = [];
  const observer = new MutationObserver(() => { if (live.textContent) messages.push(live.textContent); });
  observer.observe(live, { subtree: true, childList: true, characterData: true });
  const part = id("prt"); f.emit({ type: "part.start", part_id: part, kind: "text", index: 0 });
  for (let i = 0; i < 50; i++) {
    f.emit({ type: "text.delta", part_id: part, delta: i === 0 ? "Use \\(v=14\\) and " : "one " });
    await act(async () => {});
    expect(live.textContent).toBe("");
    expect(messages).toEqual([]);
  }
  f.emit({ type: "part.end", part_id: part, status: "complete", duration_ms: 1 });
  await act(async () => {});
  expect(messages).toHaveLength(1); expect(messages[0]).toContain("Jana:"); expect(messages[0]).toContain("Use");
  expect(live.querySelector("math")).not.toBeNull();
  const unchanged = live.innerHTML;
  const board = id("brd"), step = id("stp");
  f.emit({ type: "board.open", board_id: board, part_id: id("prt"), problem: { text: "Synthetic", latex: null } });
  const line = { board_id: board, step_id: step, index: 0, latex: "v=14", reason: null, owner: "student", check_id: null, error: null };
  for (let i = 0; i < 50; i++) {
    f.emit({ type: "board.step", ...line, status: "checking", latex: `v=${i}` }); await act(async () => {});
    expect(live.innerHTML).toBe(unchanged); expect(messages).toHaveLength(1);
  }
  f.emit({ type: "board.step", ...line, status: "correct", check_id: id("chk") }); await act(async () => {});
  expect(messages).toHaveLength(2); expect(messages[1]).toContain("Step 1, You,"); expect(messages[1]).toContain("Checked");
  expect(live.querySelector("math")).not.toBeNull();
  f.emit({ type: "board.step", ...line, status: "correct", check_id: f.holder.getState().boards[board]?.steps[step]?.check_id });
  const interrupted = f.text("This partial reply must stay quiet", false);
  f.emit({ type: "part.end", part_id: interrupted, status: "interrupted", duration_ms: 1 });
  f.end(); await act(async () => {}); expect(messages).toHaveLength(2);
  observer.disconnect();
  cleanup();
  // Loading the settled transcript is history, not a fresh announcement.
  const replay = f.render(<TutorAnnouncements sessionId={SESSION} />);
  expect(replay.container.querySelector("[aria-live]")?.textContent).toBe("");
});

test("status speech waits three seconds and excludes ticking counters", () => {
  vi.useFakeTimers(); vi.setSystemTime(1_000_000);
  const f = new Fixture(), turn = f.startTurn();
  f.status("preparing");
  const { container } = f.render(<TurnView turnId={turn} />);
  act(() => vi.advanceTimersByTime(1_000));
  expect(container.querySelector('[role="status"]')?.getAttribute("aria-live")).toBe("off");
  expect(container.querySelector("[data-status-announcement]")?.textContent).toBe("");
  f.status("waiting_first_token");
  act(() => vi.advanceTimersByTime(2_999));
  expect(container.querySelector("[data-status-announcement]")?.textContent).toBe("");
  act(() => vi.advanceTimersByTime(251));
  expect(container.querySelector("[data-status-announcement]")?.textContent).toBe("Thinking about your question");
  act(() => vi.advanceTimersByTime(5_000));
  expect(container.querySelector("[data-status-announcement]")?.textContent).toBe("Thinking about your question");
});
