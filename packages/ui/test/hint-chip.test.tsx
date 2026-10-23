// T1, hints the student pulls (LRN-20, D112): in guided mode the hint chip above the composer counts the ladder up
// from the engine's rung and asks exactly as "I'm stuck" does; the engine's unprompted offer is one quiet line under
// the conversation, never a card to answer, so it is on screen once (the question dock mirrors open question cards, which
// is how the old offer card showed twice in a row on 2026-10-19).
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { SessionController } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { TutorScreen } from "../src/TutorScreen.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { Fixture, SESSION, id } from "./harness.js";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const OFFER = "Take your time. A hint is one tap away when you want it.";

function double(): SessionController {
  return {
    sessionId: SESSION,
    answerCard: vi.fn(async () => "accepted"),
    setMode: vi.fn(async () => undefined),
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

function hintOffer(f: Fixture): void {
  f.emit({ type: "notice", notice_id: id("ntc"), level: "info", code: "hint_offer", message_key: "notice.hint_offer", params: {}, action: null });
}

test("t1_hint_chip_counts_the_ladder", () => {
  const f = new Fixture();
  f.startTurn(); f.text("Your first line is on the board. What could you do to both sides next?"); f.end();
  const session = double();
  show(f, session, <TutorScreen sessionId={SESSION} />);
  const chip = screen.getByRole("button", { name: "Hint 1 of 5" });
  expect(chip.getAttribute("data-tone")).toBe("hint");
  expect(screen.queryByRole("button", { name: "Next hint" })).toBeNull();
  fireEvent.click(chip);
  expect(vi.mocked(session.sendCapture).mock.calls[0]?.[1]).toBe("stuck"); // exactly as "I'm stuck" asks
  // The engine raised the rung (its `session.updated`), the hint was tried and closed: the chip counts on.
  act(() => { f.startTurn(); f.text("Look here: the 4 is multiplying the bracket."); f.emit({ type: "session.updated", hint_rung: 2 }); f.end(); });
  expect(screen.getByRole("button", { name: "Hint 3 of 5" })).toBeDefined();
  act(() => { f.startTurn(); f.emit({ type: "session.updated", hint_rung: 5 }); f.text("That step is shown on the board."); f.end(); });
  expect(screen.getByRole("button", { name: "Hint 5 of 5" })).toBeDefined(); // never past the ladder
  // A new step starts the ladder again.
  act(() => { f.startTurn(); f.emit({ type: "session.updated", hint_rung: 0 }); f.text("Right. Next line?"); f.end(); });
  expect(screen.getByRole("button", { name: "Hint 1 of 5" })).toBeDefined();
});

test("t1_hint_chip_only_in_guided_mode", () => {
  const f = new Fixture();
  f.startTurn(); f.text("Here is the worked solution."); f.end();
  act(() => { f.emit({ type: "session.updated", mode: "solution" }); });
  show(f, double(), <TutorScreen sessionId={SESSION} />);
  expect(screen.queryByRole("button", { name: /^Hint \d of 5$/ })).toBeNull();
  expect(screen.getByRole("button", { name: "I'm stuck" })).toBeDefined();
});

test("t1_quiet_offer_once", () => {
  const f = new Fixture();
  f.startTurn(); f.text("Your first line is on the board. What could you do to both sides next?"); f.end();
  // The idle trigger's offer: an engine-written turn whose only content is the quiet line.
  f.startTurn(); hintOffer(f); f.end();
  show(f, double(), <TutorScreen sessionId={SESSION} />);
  const lines = screen.getAllByText(OFFER);
  expect(lines).toHaveLength(1); // once: not in the transcript and again in the dock
  const turn = lines[0]!.closest("[data-hint-offer-turn]");
  expect(turn).not.toBeNull();
  expect(turn!.textContent).toBe(OFFER); // no name, no reply actions, no timing
  expect(document.querySelector("[data-request-dock]")).toBeNull();
  expect(screen.queryByRole("button", { name: /not now/i })).toBeNull();
  expect(screen.getByRole("button", { name: "Hint 1 of 5" })).toBeDefined(); // the chip is the way to take it up
  // The reply above keeps its actions in view: the offer's turn does not count as the newest reply.
  expect(document.querySelector("[data-reply-actions]")!.className).not.toContain("opacity-0");
  // The line is about now: once the student replies and the tutor answers, it is gone.
  act(() => { f.send("x - 2 = 80"); f.startTurn(); f.text("Look here: the 4 is multiplying the bracket."); f.end(); });
  expect(screen.queryByText(OFFER)).toBeNull();
});

test("t1_offer_after_a_wrong_answer_sits_under_the_reply", () => {
  const f = new Fixture();
  f.startTurn(); f.text("Look here: the 4 is multiplying the bracket. What undoes multiplying by 4?"); hintOffer(f); f.end();
  show(f, double(), <TutorScreen sessionId={SESSION} />);
  const reply = screen.getByText(/What undoes multiplying by 4/);
  const line = screen.getByText(OFFER);
  expect(reply.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getAllByText(OFFER)).toHaveLength(1);
});

test("t1_old_offer_card_was_shown_twice", () => {
  // The cause of the duplicate on 2026-10-19: an open question card is mirrored in the dock above the composer (by
  // design, so it can be answered without scrolling), right under the same card at the foot of the conversation. The
  // old offer was such a card; the quiet line is not, so it cannot be mirrored.
  const f = new Fixture();
  f.startTurn();
  const part = id("prt");
  f.emit({ type: "part.start", part_id: part, kind: "card", index: 0 });
  f.emit({ type: "card.open", request_id: id("req"), part_id: part, call_id: null, card: { card_type: "question", prompt: "Want a hint for this step?", options: [{ id: "opt_1", label: "Yes, give me a hint", recommended: true }, { id: "opt_2", label: "Not now, I'll keep trying", recommended: false }], allow_free_text: false, multi: false } });
  f.emit({ type: "part.end", part_id: part, status: "complete", duration_ms: 1 });
  f.end();
  show(f, double(), <TutorScreen sessionId={SESSION} />);
  expect(screen.getAllByText("Want a hint for this step?")).toHaveLength(2);
});
