// UXS-44: "Report a problem" on every tutor reply and every tutor line of the board, in the gallery and in a scripted
// session, by pointer and by keyboard: a finished reply's action row holds the button in the Tab order, a tutor board
// line's menu holds the choice and is reached with the arrow keys, and either opens the report sheet, which Escape
// closes with focus back where it was. Saving writes one local record with the reply's turn (the M23 local report API).
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { SessionController } from "@jana/client-core";
import { GalleryView, STATES } from "../gallery/index.js";
import { Board } from "../src/board/Board.js";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { Transcript } from "../src/transcript/Transcript.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(cleanup);

const REPORT = "Report a problem";

/** In the Tab order: a button that is enabled and not taken out of the order. */
function tabbable(button: HTMLElement): boolean {
  return button.tagName === "BUTTON" && !(button as HTMLButtonElement).disabled && button.tabIndex >= 0 && button.closest("[aria-hidden='true'],[inert]") === null;
}

/** Every finished tutor reply with something in it carries the report button in its action row, reachable by Tab. */
function expectReportOnEveryReply(root: HTMLElement, pseudo = false): number {
  let replies = 0;
  for (const turn of root.querySelectorAll<HTMLElement>("section[data-turn-id]")) {
    const row = turn.querySelector<HTMLElement>("[data-reply-actions]");
    const live = row === null;
    if (live) {
      expect(turn.querySelector("[role='status']"), turn.outerHTML).not.toBeNull();
      continue;
    }
    if (turn.querySelector("[data-part-id]") === null) continue;
    // The button by its mark (the pseudo-locale state words it differently), named as the catalogue says elsewhere.
    const button = row.querySelector<HTMLElement>("button[data-report-problem]");
    expect(button, turn.outerHTML).not.toBeNull();
    expect(button!.getAttribute("aria-label")).toBeTruthy();
    if (!pseudo) expect(button!.getAttribute("aria-label")).toBe(REPORT);
    expect(tabbable(button!)).toBe(true);
    replies += 1;
  }
  return replies;
}

function recordingSession(fixture: Fixture, reports: Record<string, unknown>[]) {
  return new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, fixture.holder, SESSION, {
    fetch: async (url, init) => {
      if (String(url).endsWith("/problem-reports") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        reports.push(body);
        return new Response(JSON.stringify({ ...body, report_id: "0".repeat(26), created_at: "2026-10-16T09:00:00.000Z", expires_at: "2027-10-16T09:00:00.000Z" }));
      }
      return new Response(JSON.stringify({ captures: [] }));
    },
  });
}

describe("UXS-44", () => {
  test("uxs44_report_on_every_reply", async () => {
    // The gallery: every finished reply of every tutor-turn and transcript state, and every tutor line of the boards.
    let replies = 0;
    for (const state of STATES.filter((s) => s.component === "TutorTurn" || s.component === "Transcript")) {
      const { container } = render(<GalleryView state={state} />);
      replies += expectReportOnEveryReply(container, (state.context.locale ?? "en") !== "en");
      cleanup();
    }
    expect(replies).toBeGreaterThan(0);
    let lines = 0;
    for (const state of STATES.filter((s) => s.component === "Board" || s.component === "BoardStep")) {
      const { container } = render(<GalleryView state={state} />);
      for (const line of container.querySelectorAll<HTMLElement>("li[data-step-id]")) {
        const tutor = line.querySelector(".text-board-tutor-line") !== null;
        const menu = line.querySelector<HTMLElement>("[data-line-menu] button[aria-haspopup='menu']");
        expect(menu !== null, `${state.id} ${line.getAttribute("data-step-id")}`).toBe(tutor);
        if (menu !== null) {
          expect(tabbable(menu)).toBe(true);
          lines += 1;
        }
      }
      cleanup();
    }
    expect(lines).toBeGreaterThan(0);

    // A scripted session: three replies, the middle one with a tool line, the last still being written.
    const fixture = new Fixture();
    const turns: string[] = [];
    for (const words of ["First reply.", "Second reply.", "Third reply."]) {
      fixture.send(words);
      turns.push(fixture.startTurn());
      if (words.startsWith("Second")) fixture.tool("check_working");
      fixture.text(words);
      if (!words.startsWith("Third")) fixture.end();
    }
    const reports: Record<string, unknown>[] = [];
    const session = recordingSession(fixture, reports);
    try {
      const { container } = render(
        <LocaleProvider locale="en"><RegistryProvider registry={defaultRegistry()}><StoreProvider holder={fixture.holder} session={session}>
          <Transcript sessionId={SESSION} />
        </StoreProvider></RegistryProvider></LocaleProvider>,
      );
      expect(expectReportOnEveryReply(container)).toBe(2); // the reply still being written has no action row yet
      // By keyboard: focus the button and activate it; the sheet opens on the reply and Escape gives focus back.
      const second = container.querySelector<HTMLElement>(`section[data-turn-id="${turns[1]}"] [data-reply-actions]`)!;
      const button = within(second).getByRole("button", { name: REPORT });
      button.focus();
      expect(document.activeElement).toBe(button);
      fireEvent.click(button);
      const sheet = screen.getByRole("dialog", { name: REPORT });
      expect(within(sheet).getByRole("group", { name: "What's the problem?" })).toBeTruthy();
      fireEvent.keyDown(sheet, { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.activeElement).toBe(button);
      // Saving names that reply's turn, on this computer only.
      fireEvent.click(button);
      fireEvent.click(screen.getByRole("radio", { name: "It's confusing" }));
      fireEvent.click(screen.getByRole("button", { name: "Save report" }));
      await screen.findByText("Thanks. Your report is saved on this computer. You can send it to us from Settings, under Help.");
      expect(reports).toEqual([{ session_id: SESSION, turn_ids: [turns[1]], category: "confusing", note: "", allow_support_export: false }]);
    } finally {
      session.close();
    }
  });

  test("a tutor line's menu reports the reply that wrote the board", async () => {
    const fixture = new Fixture();
    fixture.send("A question.");
    const turn = fixture.startTurn();
    const partId = fixture.text("Let us set it out.");
    const board = "brd_" + "1".repeat(26);
    fixture.emit({ type: "board.reset", board_id: board, part_id: partId, problem: null });
    fixture.emit({ type: "board.step", board_id: board, step_id: "stp_" + "1".repeat(26), index: 0, latex: "v^2 = u^2 + 2as", reason: null, owner: "tutor", status: "final", check_id: null, error: null });
    fixture.emit({ type: "board.step", board_id: board, step_id: "stp_" + "2".repeat(26), index: 1, latex: "v = 14", reason: null, owner: "student", status: "awaiting", check_id: null, error: null });
    fixture.end();
    const reports: Record<string, unknown>[] = [];
    const session = recordingSession(fixture, reports);
    try {
      render(
        <LocaleProvider locale="en"><RegistryProvider registry={defaultRegistry()}><StoreProvider holder={fixture.holder} session={session}>
          <Board sessionId={SESSION} />
        </StoreProvider></RegistryProvider></LocaleProvider>,
      );
      // The student's own line has no report menu; the tutor's has one, opened and walked by keyboard.
      expect(screen.queryByRole("button", { name: "More for step 2" })).toBeNull();
      const trigger = screen.getByRole("button", { name: "More for step 1" });
      fireEvent.click(trigger);
      const menu = screen.getByRole("menu", { name: "More for step 1" });
      const choice = within(menu).getByRole("menuitem", { name: REPORT });
      expect(document.activeElement).toBe(choice);
      fireEvent.keyDown(menu, { key: "End" });
      expect(document.activeElement).toBe(choice);
      fireEvent.click(choice);
      fireEvent.click(screen.getByRole("radio", { name: "It isn't right" }));
      fireEvent.click(screen.getByRole("button", { name: "Save report" }));
      await screen.findByText("Thanks. Your report is saved on this computer. You can send it to us from Settings, under Help.");
      expect(reports).toEqual([{ session_id: SESSION, turn_ids: [turn], category: "incorrect", note: "", allow_support_export: false }]);
      await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Close" }).at(-1)!); });
      expect(screen.queryByRole("dialog")).toBeNull();
    } finally {
      session.close();
    }
  });
});
