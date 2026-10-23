// UXS-24 and API-27 in the app as it is wired: Practice (the sidebar's place and Ctrl+3) starts a set from the core,
// marks each answer at once in the UXS-16 words (a "look here" note from the first error, then Checked with the mastery
// change and Next question), and a help chip opens the tutor with the item loaded and asks for that help, whose header
// leads back to the same question with the answer being written still there. Help comes before the answer (ASM-28): a
// first miss shows no answer and keeps the question for a second try; the worked answer, with its checks, follows the
// second miss or Don't know. A core that does not serve practice sets says so and offers
// Learn. Against the fake core, with the gallery's lesson items (built from the repository's curriculum sources).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { STATES } from "@jana/ui/gallery";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

type Item = Record<string, unknown> & { item_id: string };
const LESSON = STATES.find((s) => s.id === "lesson-player.canonical")!.payload as { lesson: { blocks: { items?: Item[] }[] } };
const ITEMS = LESSON.lesson.blocks.flatMap((b) => b.items ?? []).slice(0, 3);

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({
  matches: !query.includes("prefers-color-scheme"), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined,
  addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
})));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(serve = true) {
  const core = new FakeProfileCore();
  core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  core.practiceServed = serve;
  core.practiceItems = ITEMS;
  render(<App runtime={createRuntime(core.launch, core.fetch)} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
  const nav = await screen.findByRole("navigation", { name: "Main" });
  return { core, nav };
}

const answer = (value: string, unit: string) => {
  fireEvent.change(screen.getByLabelText("Your answer"), { target: { value } });
  fireEvent.change(screen.getByLabelText("Unit"), { target: { value: unit } });
};

describe("UXS-24", () => {
  test("test_uxs24_practice_marks_each_try", async () => {
    const { core, nav } = await open();
    core.mark = (_item, _parts) => ({ verdict: "incorrect", category: "units" });
    fireEvent.click(within(nav).getByRole("button", { name: "Practice" }));
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    expect(within(nav).getByRole("button", { name: "Practice" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("progressbar", { name: "Practice progress" }).getAttribute("aria-valuetext")).toBe("Question 1 of 3");
    expect(core.log.find((r) => r.path === "/v1/practice/sets")?.body).toMatchObject({ subject: "physics", source: "adaptive", size: 5 });
    // A try that is not right: "Not quite" and the look-here words of its first error, never the word "wrong".
    answer("1.2", "m/s");
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    const first = await waitFor(() => {
      const found = document.querySelector("[data-try='1']");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(first.textContent).toContain("Try 1: 1.2 m/s");
    expect(first.textContent).toContain("Not quite");
    expect(first.textContent).toContain("Look at the units");
    expect(first.querySelector("svg")).not.toBeNull();
    expect(document.body.textContent?.toLowerCase()).not.toContain("wrong");
    // A first miss keeps the question for a second try (ASM-28): no answer, no Next question yet.
    expect(first.textContent).toContain("Have another go");
    expect(within(first).queryByRole("button", { name: "Next question" })).toBeNull();
    answer("1.3", "m/s");
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    const worked = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-worked]");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(document.querySelector("[data-try='2']")?.textContent).toContain("Not quite");
    expect(screen.queryByRole("button", { name: "Check again" })).toBeNull();
    fireEvent.click(within(worked).getByRole("button", { name: "Next question" }));
    await waitFor(() => expect(screen.getByRole("progressbar", { name: "Practice progress" }).getAttribute("aria-valuetext")).toBe("Question 2 of 3"));
    expect(document.querySelector("[data-try]")).toBeNull();
    expect(document.querySelector(`[data-item-id="${ITEMS[1]!.item_id}"]`)).not.toBeNull();
    // A right answer: Checked, the mastery change in words, and Next question.
    core.mark = () => ({ verdict: "correct", category: null });
    answer("1.2", "m/s");
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    const second = await waitFor(() => {
      const found = document.querySelector("[data-try='1']");
      expect(found?.getAttribute("data-verdict")).toBe("correct");
      return found as HTMLElement;
    });
    expect(second.textContent).toContain("Checked");
    expect(second.textContent).toContain("This idea moved from Learning to Secure.");
    fireEvent.click(within(second).getByRole("button", { name: "Next question" }));
    await waitFor(() => expect(screen.getByRole("progressbar", { name: "Practice progress" }).getAttribute("aria-valuetext")).toBe("Question 3 of 3"));
    expect(document.querySelector(`[data-item-id="${ITEMS[2]!.item_id}"]`)).not.toBeNull();
    // The last question's mark ends the set: "Finish the set", then the set is done.
    answer("1.2", "m/s");
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    fireEvent.click(await screen.findByRole("button", { name: "Finish the set" }));
    await waitFor(() => expect(document.querySelector("[data-practice-done]")).not.toBeNull());
  });

  test("uxs24_help_me_round_trip", () => verifyReturnContext(0));

  test.each([0, 1])("uxs01_tutor_return_context: question %s", verifyReturnContext);

  test("test_uxs24_units_typeset_as_on_the_board", async () => {
    const { core, nav } = await open();
    core.mark = () => ({ verdict: "incorrect", category: "units" });
    fireEvent.click(within(nav).getByRole("button", { name: "Practice" }));
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    // The unit field keeps what was typed and echoes a unit with a power typeset beside it; a plain unit has no echo.
    answer("2", "m/s");
    expect(document.querySelector("[data-unit-echo]")).toBeNull();
    answer("2", "m/s^2");
    expect((screen.getByLabelText("Unit") as HTMLInputElement).value).toBe("m/s^2");
    const echo = document.querySelector<HTMLElement>("[data-unit-echo]")!;
    expect(echo.querySelector(".katex")).not.toBeNull();
    expect(echo.getAttribute("aria-hidden")).toBe("true");
    // The try shows the unit typeset too, never the caret.
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    const first = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-try='1']");
      expect(found).not.toBeNull();
      return found!;
    });
    const unit = first.querySelector<HTMLElement>("[data-unit-typeset]")!;
    expect(unit.querySelector(".katex-html")).not.toBeNull();
    expect(first.querySelector(".katex-html")!.textContent).not.toContain("^");
    expect(first.querySelector("p")!.firstChild?.textContent).toBe("Try 1: ");
  });

  test("test_asm28_no_reveal_on_first_miss", async () => {
    const { core, nav } = await open();
    core.mark = () => ({ verdict: "incorrect", category: null });
    fireEvent.click(within(nav).getByRole("button", { name: "Practice" }));
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    // Every practice question offers the three help chips (ASM-28).
    const chips = screen.getByRole("group", { name: "Help with this question" });
    expect(within(chips).getAllByRole("button").map((b) => b.textContent)).toEqual(["Give me a hint", "Walk me through it", "Explain simply"]);
    answer("1.2", "m/s");
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    await waitFor(() => expect(document.querySelector("[data-try='1']")).not.toBeNull());
    // After one wrong answer the final value and the worked answer are nowhere on screen; the chips are still there.
    expect(document.body.textContent).not.toContain("1.5");
    expect(document.querySelector("[data-worked]")).toBeNull();
    expect(screen.getByRole("group", { name: "Help with this question" })).not.toBeNull();
    // Don't know: the worked answer with each step's check and the verified key's check.
    fireEvent.click(screen.getByRole("button", { name: "Don't know" }));
    const worked = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-worked]");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(core.log.some((r) => /\/reveal$/.test(r.path))).toBe(true);
    expect(worked.querySelector("[data-check-id='chk_fake_key'] .katex")).not.toBeNull();
    expect(worked.textContent).toContain("Speed is distance over time");
    fireEvent.click(within(worked).getByRole("button", { name: "Next question" }));
    await waitFor(() => expect(screen.getByRole("progressbar", { name: "Practice progress" }).getAttribute("aria-valuetext")).toBe("Question 2 of 3"));
    expect(document.querySelector("[data-worked]")).toBeNull();
  });

  test("test_api27_practice_not_served_says_so", async () => {
    await open(false);
    fireEvent.keyDown(window, { key: "3", code: "Digit3", ctrlKey: true }); // Ctrl+3: Practice (LOC-12)
    await screen.findByText("Practice sets aren't on this computer yet. The quick checks in each lesson work now.");
    fireEvent.click(screen.getByRole("button", { name: "Browse topics" }));
    await screen.findByRole("heading", { level: 1, name: /Physics|Learn/ });
  });
});


async function verifyReturnContext(index: number) {

    const { core, nav } = await open();
    fireEvent.click(within(nav).getByRole("button", { name: "Practice" }));
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    if (index > 0) {
      core.mark = () => ({ verdict: "correct", category: null });
      answer("1.2", "m/s");
      fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
      fireEvent.click(await screen.findByRole("button", { name: "Next question" }));
      await waitFor(() => expect(screen.getByRole("progressbar", { name: "Practice progress" }).getAttribute("aria-valuetext")).toBe("Question 2 of 3"));
    }
    answer("0.9", "m/s");
    const turns = core.turnsStarted;
    fireEvent.click(screen.getByRole("button", { name: "Give me a hint" }));
    // The tutor opens with the item loaded; its header leads back to the same question.
    const back = await screen.findByRole("button", { name: `Back to practice question ${index + 1}` });
    expect(core.helped).toEqual([ITEMS[index]!.item_id]);
    // The tutor is asked for the hint at once, as the hint ladder's next rung (intent stuck, ASM-28, LRN-20).
    await waitFor(() => expect(core.turnsStarted).toBe(turns + 1));
    expect(core.log.filter((r) => /\/turns$/.test(r.path)).at(-1)?.body).toMatchObject({ intent: "stuck", content: [{ type: "text", text: "Give me a hint" }] });
    fireEvent.click(back);
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    expect(document.querySelector(`[data-item-id="${ITEMS[index]!.item_id}"]`)).not.toBeNull();
    expect((screen.getByLabelText("Your answer") as HTMLInputElement).value).toBe("0.9");
    expect((screen.getByLabelText("Unit") as HTMLInputElement).value).toBe("m/s");
    expect(core.log.filter((r) => r.path === "/v1/practice/sets")).toHaveLength(1); // the same set, not a new one

}
