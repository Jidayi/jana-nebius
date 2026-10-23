// The tutor workspace's controls of stage 3: the hint dock in step with the hint card (UXS-17), the mode menu (UXS-18),
// "Let support see this session" (OBS-18) and the calm screen over the workspace (UXS-43). Against a store fed with
// events, as the session controller feeds it, and a session double that records what the workspace asks of the core.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { SessionController } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { TutorScreen } from "../src/TutorScreen.js";
import { LessonLinkProvider } from "../src/learn/link.js";
import { CalmScreen } from "../src/safety/CalmScreen.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { Fixture, SESSION, id } from "./harness.js";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BOARD = `brd_${"8".repeat(26)}`;

function double(f: Fixture) {
  const answered: [string, Record<string, unknown>][] = [];
  const modes: string[] = [];
  const posts: string[] = [];
  const session = {
    sessionId: SESSION,
    answerCard: vi.fn(async (requestId: string, answer: Record<string, unknown>) => {
      answered.push([requestId, answer]);
      act(() => f.holder.update((s) => ({ ...s, requests: { ...s.requests, [requestId]: { ...s.requests[requestId]!, state: "answering" } } })));
      return "accepted";
    }),
    setMode: vi.fn(async (mode: string) => { modes.push(mode); }),
    commands: {
      post: vi.fn(async (path: string) => { posts.push(path); return undefined; }),
      get: vi.fn(async () => ({ captures: [] })), put: vi.fn(async () => undefined), patch: vi.fn(async () => undefined), delete: vi.fn(async () => undefined),
    },
    send: vi.fn(), sendCapture: vi.fn(), cancel: vi.fn(), discardFailed: vi.fn(), retryTurn: vi.fn(async () => undefined),
  } as unknown as SessionController;
  return { session, answered, modes, posts };
}

function show(f: Fixture, session: SessionController, node: ReactNode) {
  return render(
    <LocaleProvider locale="en">
      <RegistryProvider registry={defaultRegistry()}>
        <StoreProvider holder={f.holder} session={session}>{node}</StoreProvider>
      </RegistryProvider>
    </LocaleProvider>,
  );
}

function hintTurn(f: Fixture): string {
  f.startTurn();
  const part = id("prt");
  const requestId = id("req");
  f.emit({ type: "part.start", part_id: part, kind: "card", index: 0 });
  f.emit({ type: "card.open", request_id: requestId, part_id: part, call_id: null, card: { card_type: "hint", rung: 2, of: 5, body: "Which way does gravity pull?", actions: ["try_it", "next_hint", "show_step"] } });
  f.emit({ type: "part.end", part_id: part, status: "complete", duration_ms: 1 });
  f.end();
  return requestId;
}

describe("UXS-17", () => {
  test("uxs17_dock_card_sync", () => {
    const f = new Fixture();
    const requestId = hintTurn(f);
    const { session, answered } = double(f);
    show(f, session, <TutorScreen sessionId={SESSION} />);
    // In guided mode the dock replaces the action row with the hint card's own actions.
    const dock = screen.getByRole("group", { name: "Hints" });
    expect(within(dock).getAllByRole("button").map((b) => b.textContent)).toEqual(["Try it", "Next hint (3 of 5)", "Show this step (counts as not yet mastered)", "Show solution"]);
    expect(screen.queryByRole("button", { name: "I'm stuck" })).toBeNull();
    // Alt+H asks for the next hint: the same request the card answers, and then both wait together.
    fireEvent.keyDown(window, { key: "h", code: "KeyH", altKey: true });
    expect(answered).toEqual([[requestId, { action: "next_hint" }]]);
    for (const button of within(dock).getAllByRole("button")) expect((button as HTMLButtonElement).disabled).toBe(true);
    const card = screen.getByRole("region", { name: "Hint 2 of 5" });
    expect((within(card).getByRole("button", { name: "Another hint" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dock).getByRole("button", { name: "Try it" }));
    expect(answered).toHaveLength(1); // one press does one thing
  });
});

describe("UXS-18", () => {
  test("test_uxs18_mode_menu_reaches_solution", () => {
    const f = new Fixture();
    hintTurn(f);
    const { session, modes } = double(f);
    show(f, session, <TutorScreen sessionId={SESSION} />);
    const chip = screen.getByRole("button", { name: "Mode: Guided" });
    expect(chip.getAttribute("aria-haspopup")).toBe("menu");
    fireEvent.click(chip);
    const menu = screen.getByRole("menu", { name: "Mode" });
    const choices = within(menu).getAllByRole("menuitemradio");
    expect(choices.map((c) => [c.textContent, c.getAttribute("aria-checked")])).toEqual([["Guided", "true"], ["Solution", "false"], ["Check my working", "false"]]);
    expect(document.activeElement).toBe(choices[0]);
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(choices[1]);
    fireEvent.click(choices[1]!);
    expect(modes).toEqual(["solution"]);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(chip);
    // The dock's "Show solution" reaches the same mode at any time (D87).
    fireEvent.click(within(screen.getByRole("group", { name: "Hints" })).getByRole("button", { name: "Show solution" }));
    expect(modes).toEqual(["solution", "solution"]);
  });
});

describe("OBS-18", () => {
  test("test_obs18_student_lets_support_see_a_session", async () => {
    const f = new Fixture();
    hintTurn(f);
    const { session, posts } = double(f);
    show(f, session, <TutorScreen sessionId={SESSION} />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Let support see this session" }));
    const confirm = screen.getByRole("alertdialog", { name: "Let support see this session?" });
    expect(confirm.textContent).toContain("Nothing is sent from here.");
    expect(posts).toEqual([]); // nothing until the student confirms
    await act(async () => fireEvent.click(within(confirm).getByRole("button", { name: "Let support see it" })));
    expect(posts).toEqual([`/v1/sessions/${SESSION}/support-share`]);
    expect(await screen.findByText("Support can see this session in a report you save.")).toBeTruthy();
  });
});

describe("UXS-43", () => {
  function distress(f: Fixture) {
    f.emit({ type: "board.step", board_id: BOARD, step_id: `stp_${"1".repeat(26)}`, index: 0, latex: "v = u + at", reason: null, owner: "tutor", status: "final", check_id: null, error: null }, null);
    f.startTurn();
    f.text("It sounds like things are really hard right now. You don't have to deal with this on your own.");
    f.emit({ type: "notice", notice_id: id("ntc"), level: "info", code: "calm_screen", message_key: "safety.calm_screen", params: {}, action: null });
    f.end();
  }

  test("uxs43_calm_screen_only", () => {
    const f = new Fixture();
    const { session } = double(f);
    distress(f);
    show(f, session, <TutorScreen sessionId={SESSION} helplines={[{ name: "Sample helpline (fixture)", number: "0000 000 000", hours: "Every day, all day" }]} />);
    const calm = document.querySelector<HTMLElement>("[data-calm-screen]")!;
    expect(calm).not.toBeNull();
    // The template's words, the heading, the helplines and one action; nothing else, and nothing that moves.
    expect(calm.textContent).toContain("You don't have to deal with this on your own.");
    expect(within(calm).getByRole("heading", { name: "Talk to someone you trust" })).toBeTruthy();
    expect(within(calm).getByText("0000 000 000")).toBeTruthy();
    expect(within(calm).getAllByRole("button").map((b) => b.textContent)).toEqual(["Back to my lesson when I'm ready"]);
    expect(calm.getAttribute("data-reduced-motion")).toBe("true"); // instant whatever the motion setting
    expect([...calm.querySelectorAll("[class*='jana-']")].flatMap((el) => [...el.classList].filter((c) => c.startsWith("jana-")))).toEqual(["jana-press"]);
    expect(calm.querySelectorAll("[role='progressbar'], [role='timer']")).toHaveLength(0);
    expect(calm.textContent).not.toMatch(/report a problem|rate|distress/i);
    // The notice is the calm screen, never a line in the conversation.
    expect(document.body.textContent).not.toContain("safety.calm_screen");
    // With no verified helpline, only the words and the way back.
    cleanup();
    render(<LocaleProvider locale="en"><CalmScreen text="Words." helplines={[]} onBack={() => undefined} /></LocaleProvider>);
    expect(document.querySelector("[data-helplines]")).toBeNull();
  });

  test("uxs43_back_returns_to_lesson", () => {
    const f = new Fixture();
    const { session } = double(f);
    distress(f);
    show(f, session, <TutorScreen sessionId={SESSION} />);
    // The workspace stays where it was under the calm screen, out of reach until the student goes back.
    const board = document.querySelector<HTMLElement>("[data-step-id]")!;
    expect(board).not.toBeNull();
    expect(board.closest("[inert]")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Back to my lesson when I'm ready" }));
    expect(document.querySelector("[data-calm-screen]")).toBeNull();
    expect(document.querySelector("[data-step-id]")).toBe(board); // the same board, not drawn again
    expect(board.closest("[inert]")).toBeNull();
  });
});

test("uxs17_attempt_before_hint", () => {
  const f = new Fixture();
  f.startTurn(); f.text("Try one line of the problem."); f.end();
  const { session } = double(f);
  show(f, session, <TutorScreen sessionId={SESSION} />);
  const next = screen.getByRole("button", { name: "Hint 1 of 5" }) as HTMLButtonElement;
  expect(next.disabled).toBe(false);
  fireEvent.click(next);
  expect(session.sendCapture).toHaveBeenCalledTimes(1);
  expect(vi.mocked(session.sendCapture).mock.calls[0]?.[1]).toBe("stuck");
  act(() => { f.startTurn(); f.text("Before a hint: what does the question give you, and what does it ask for?"); f.end(); });
  expect(screen.getAllByText("Before a hint: what does the question give you, and what does it ask for?").filter((element) => element.closest("[data-part-id]"))).toHaveLength(1);
  const again = screen.getByRole("button", { name: "Hint 1 of 5" }) as HTMLButtonElement;
  expect(again.disabled).toBe(false);
  fireEvent.click(again);
  expect(session.sendCapture).toHaveBeenCalledTimes(2);
  expect(vi.mocked(session.sendCapture).mock.calls[1]?.[1]).toBe("stuck");
});


test("a completed crash offers retry only while it is the last turn of an idle session", () => {
  const f = new Fixture();
  const failed = f.startTurn();
  f.emit({ type: "board.step", board_id: BOARD, step_id: id("stp"), index: 2, latex: "s=10", owner: "student", status: "correct", check_id: "chk_saved", error: null, reason: null });
  f.emit({ type: "error", code: "model_unavailable", message: "Synthetic failure", retryable: true, scope: "turn" });
  f.end("error");
  const { session } = double(f);
  show(f, session, <TutorScreen sessionId={SESSION} />);
  expect(screen.getByText("The tutor stopped unexpectedly. Your work up to step 3 is saved.")).toBeDefined();
  const retry = screen.getByRole("button", { name: "Try again" }) as HTMLButtonElement;
  expect(retry.disabled).toBe(false); fireEvent.click(retry);
  expect(session.retryTurn).toHaveBeenCalledWith(failed);
  act(() => { f.startTurn(); f.text("A new reply has begun.", false); });
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
});


test("special-state topic and lesson actions call the installed-content navigator", () => {
  const f = new Fixture(); f.startTurn();
  f.emit({ type: "notice", notice_id: id("ntc"), level: "info", code: "beyond_level", message_key: "notice.beyond_level_topic", params: { title: "Forces" }, action: { label_key: "notice.open_topic", command: "open_topic:cur.phy.o.forces" } });
  f.emit({ type: "notice", notice_id: id("ntc"), level: "info", code: "tutor_unsure", message_key: "notice.tutor_unsure", params: { title: "Gravity" }, action: { label_key: "notice.open_lesson", command: "open_lesson:les.phy.o.gravity" } }); f.end();
  const { session } = double(f); const topic = vi.fn(); const lesson = vi.fn();
  show(f, session, <LessonLinkProvider open={lesson} openTopic={topic}><TutorScreen sessionId={SESSION} /></LessonLinkProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Open topic" }));
  fireEvent.click(screen.getByRole("button", { name: "Open lesson" }));
  expect(topic).toHaveBeenCalledExactlyOnceWith("cur.phy.o.forces");
  expect(lesson).toHaveBeenCalledExactlyOnceWith("les.phy.o.gravity");
});
