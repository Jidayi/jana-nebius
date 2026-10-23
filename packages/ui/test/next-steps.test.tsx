// M45.d (D120): follow-up chips after a reply that never carry the answer, the chat's automatic title and its rename,
// one maths renderer everywhere text shows (UXS-68); the help chips (ASM-28); the gentle daily goal (LRN-45).
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { chatTitle, followUps, goalProgress, mentionsAnswer, type PlanView, type SessionController } from "@jana/client-core";
import { FollowUpChips, FollowUpProvider, HelpChips } from "../src/chips/NextStepChips.js";
import { DailyGoalChip } from "../src/home/DailyGoal.js";
import { LocaleProvider } from "../src/i18n.js";
import { PackInline, PackText } from "../src/learn/PackText.js";
import { MarkdownBlock } from "../src/markdown/Markdown.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { TutorScreen } from "../src/TutorScreen.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function double(): SessionController {
  return {
    sessionId: SESSION,
    answerCard: vi.fn(async () => "accepted"),
    setMode: vi.fn(async () => undefined),
    rename: vi.fn(async () => undefined),
    commands: {
      post: vi.fn(async () => undefined), get: vi.fn(async () => ({ captures: [] })), put: vi.fn(async () => undefined),
      patch: vi.fn(async () => undefined), delete: vi.fn(async () => undefined),
    },
    send: vi.fn(), sendCapture: vi.fn(), cancel: vi.fn(), discardFailed: vi.fn(), retryTurn: vi.fn(async () => undefined),
  } as unknown as SessionController;
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

const en = (node: ReactNode) => render(<LocaleProvider locale="en">{node}</LocaleProvider>);

test("uxs68_chips_titles_maths", () => {
  // Chips never contain the current final answer: at most two, and one whose words name the answer is dropped.
  const words: Record<string, string> = { practise: "Practise this", flashcards: "Flashcards for 12 m/s", explain_step: "Explain a step" };
  const label = (kind: string) => words[kind] ?? kind;
  expect(followUps(["flashcards", "practise", "explain_step"], label, ["12"]).map((c) => c.kind)).toEqual(["practise", "explain_step"]);
  expect(followUps(["practise", "flashcards", "explain_step"], label).length).toBe(2);
  expect(mentionsAnswer("v = 12 m/s", ["12"])).toBe(true);
  expect(mentionsAnswer("about 120 of them", ["12"])).toBe(false);
  expect(mentionsAnswer("Choose Resultant force", ["resultant  force"])).toBe(true);

  // After the tutor's first reply: the title arrives (at most six words), two follow-ups under the reply, no answer in
  // them; choosing "Explain a step" asks the tutor, "Practise this" is the app's to open.
  const f = new Fixture();
  const session = double();
  const onChoose = vi.fn();
  f.startTurn(); f.text("A ball is thrown up at 20 m/s. The final speed at the top is 0 m/s, so think about what that tells you."); f.end();
  f.emit({ type: "session.updated", title: chatTitle("A ball is thrown up at 20 m/s. How high does it go?") });
  show(f, session, <FollowUpProvider value={{ offered: () => ["practise", "explain_step", "flashcards"], onChoose }}><TutorScreen sessionId={SESSION} /></FollowUpProvider>);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("A ball is thrown up at");
  const group = screen.getByRole("group", { name: "What next" });
  const chips = within(group).getAllByRole("button");
  expect(chips.map((c) => c.textContent)).toEqual(["Practise this", "Explain a step"]);
  for (const chip of chips) expect(mentionsAnswer(chip.textContent ?? "", ["0", "20"])).toBe(false);
  fireEvent.click(chips[1]!);
  expect(vi.mocked(session.sendCapture).mock.calls[0]?.[0].text).toBe("Can you explain that step again, a different way?");
  expect(vi.mocked(session.sendCapture).mock.calls[0]?.[1]).toBe("answer");
  expect(onChoose).toHaveBeenCalledWith("explain_step", expect.objectContaining({ sessionId: SESSION }));

  // The title can be renamed from the header's More menu.
  fireEvent.click(screen.getByRole("button", { name: "More" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
  const field = screen.getByRole("textbox", { name: "Chat name" });
  fireEvent.change(field, { target: { value: "Projectile height" } });
  fireEvent.click(screen.getByRole("button", { name: "Save name" }));
  expect(vi.mocked(session.rename)).toHaveBeenCalledWith("Projectile height");
  cleanup();

  // One expression renders identically in chat (model Markdown), cards (pack text) and quizzes (stems and options).
  const chat = en(<MarkdownBlock text={"Use \\(v = \\frac{d}{t}\\) here."} />).container.querySelector(".katex")!.outerHTML;
  cleanup();
  const card = en(<PackText text={"Use $v = \\frac{d}{t}$ here."} />).container.querySelector(".katex")!.outerHTML;
  cleanup();
  const option = en(<PackInline text={"$v = \\frac{d}{t}$"} />).container.querySelector(".katex")!.outerHTML;
  expect(card).toBe(chat);
  expect(option).toBe(chat);
});

test("test_uxs68_no_follow_ups_without_the_app_or_while_a_question_waits", () => {
  const f = new Fixture();
  f.startTurn(); f.text("Here is a step."); f.end();
  show(f, double(), <TutorScreen sessionId={SESSION} />);
  expect(screen.queryByRole("group", { name: "What next" })).toBeNull(); // no provider: no chips
  cleanup();
  en(<FollowUpChips chips={[]} onChoose={() => undefined} />);
  expect(document.querySelector("[data-follow-ups]")).toBeNull();
});

test("test_asm28_help_chips_report_the_kind", () => {
  const onHelp = vi.fn();
  en(<HelpChips onHelp={onHelp} hintKeys="Alt+H" />);
  const group = screen.getByRole("group", { name: "Help with this question" });
  const chips = within(group).getAllByRole("button");
  expect(chips.map((c) => c.textContent)).toEqual(["Give me a hint", "Walk me through it", "Explain simply"]);
  expect(chips[0]!.getAttribute("aria-keyshortcuts")).toBe("Alt+H");
  fireEvent.click(chips[1]!);
  fireEvent.click(chips[2]!);
  expect(onHelp.mock.calls.map((c) => c[0])).toEqual(["walk_through", "explain_simply"]);
});

function plan(blocks: { kind: string; status: string }[], keepLearning = false): PlanView {
  return {
    plan_id: "01HZZZZZZZZZZZZZZZZZZZZZZZ", request_id: `req_${"0".repeat(26)}`, date: "2026-10-20", phase: "normal", status: "started", minutes: 30,
    blocks: blocks.map((b, index) => ({ index, kind: b.kind, kc_ids: [], minutes: 10, status: b.status, done: 0, target: 1 })),
    next_block: 0, alternatives: [], keep_learning: keepLearning, decided_ts: null, card: {} as PlanView["card"],
  } as PlanView;
}

const SHAME = /streak|lost|missed|broke|behind|fail|again|only|yesterday|don't give up|keep it up/i;

test("lrn45_goal_without_shame", () => {
  const onChange = vi.fn();
  // A new day (or a missed one): nothing done yet reads like the start of any day, no penalty words.
  const fresh = goalProgress(plan([{ kind: "warmup", status: "pending" }, { kind: "main", status: "pending" }, { kind: "reflect", status: "pending" }]), 2);
  const first = en(<DailyGoalChip progress={fresh} onChange={onChange} />);
  const chip = screen.getByRole("button", { name: /Daily goal/ });
  expect(chip.textContent).toBe("Today: 0 of 2");
  expect(document.body.textContent).not.toMatch(SHAME);
  expect(chip.hasAttribute("data-goal-met")).toBe(false);
  first.unmount();
  // One action done, then two: the chip fills; the look back is not a study action.
  expect(goalProgress(plan([{ kind: "warmup", status: "done" }, { kind: "main", status: "in_progress" }, { kind: "reflect", status: "done" }]), 2)).toEqual({ done: 1, target: 2, met: false });
  const full = goalProgress(plan([{ kind: "warmup", status: "done" }, { kind: "main", status: "done" }, { kind: "reflect", status: "pending" }]), 2);
  expect(full).toEqual({ done: 2, target: 2, met: true });
  expect(goalProgress(plan([], true), 3).met).toBe(true); // a plan of the day already finished
  en(<DailyGoalChip progress={full} onChange={onChange} />);
  const filled = screen.getByRole("button", { name: /Daily goal/ });
  expect(filled.hasAttribute("data-goal-met")).toBe(true);
  expect(filled.textContent).toBe("Goal met today");
  expect(document.querySelectorAll("[data-goal-step='done']")).toHaveLength(2);
  // The learner can change the goal or hide it.
  fireEvent.click(filled);
  expect(screen.getAllByRole("menuitemradio").map((m) => m.textContent)).toEqual(expect.arrayContaining(["3 study actions a day"]));
  fireEvent.click(screen.getByRole("menuitemradio", { name: "3 study actions a day" }));
  expect(onChange).toHaveBeenLastCalledWith(3);
  fireEvent.click(filled);
  fireEvent.click(screen.getByRole("menuitem", { name: "Hide the daily goal" }));
  expect(onChange).toHaveBeenLastCalledWith(0);
  expect(document.body.textContent).not.toMatch(SHAME);
});
