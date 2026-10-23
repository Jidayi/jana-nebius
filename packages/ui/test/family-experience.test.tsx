// The family-experience fixes in the UI: a second question in a session with turns is sent as a question (`ask`), not
// as an attempt at the last one (PED-01); the confirm dialog keeps focus inside, closes on Escape and gives focus back
// (DSN-12); an icon-only button shows its label on focus (UXS-01); "Finish" on a lesson moves focus to the finished
// message, which is announced (UXS-23); "Report a problem" saves a report on this computer and Settings → Help lists it
// (UXS-44); the working board's photo action is not a second "Photo of a question".
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { ProfileController, SessionController, StoreHolder } from "@jana/client-core";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { STATES } from "../gallery/index.js";
import { Composer } from "../src/composer/Composer.js";
import { LocaleProvider } from "../src/i18n.js";
import { LessonPlayerContent } from "../src/learn/LessonPlayer.js";
import { ConfirmDialog, IconButton } from "../src/primitives/index.js";
import { ProblemReportList } from "../src/settings/Help.js";
import { StoreProvider } from "../src/store.js";
import { ReportProblem } from "../src/transcript/ReportProblem.js";
import { WorkingEntry } from "../src/board/WorkingEntry.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(cleanup);

const paste = (text: string) => ({ clipboardData: { getData: (type: string) => (type === "text/plain" ? text : "") } });

function recordingSession(fixture: Fixture, sent: Record<string, unknown>[], reports: Record<string, unknown>[] = []) {
  return new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, fixture.holder, SESSION, {
    fetch: async (url, init) => {
      if (String(url).endsWith("/captures")) return new Response(JSON.stringify({ captures: [] }));
      if (init?.method === "GET" || init?.method === undefined) return new Response(JSON.stringify({ revision: 0, document: { type: "doc" } }));
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      if (String(url).endsWith("/turns")) sent.push(body);
      if (String(url).endsWith("/problem-reports")) {
        reports.push(body);
        return new Response(JSON.stringify({ ...body, report_id: "0".repeat(26), created_at: "2026-10-14T09:00:00.000Z", expires_at: "2027-10-14T09:00:00.000Z" }));
      }
      return new Response(JSON.stringify({ revision: 1, turn_id: "trn_synthetic", message_id: "msg_synthetic" }), { status: 202 });
    },
  });
}

async function flush() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

describe("PED-01", () => {
  async function composeAndSend(text: string, newQuestion: boolean): Promise<Record<string, unknown> | undefined> {
    const fixture = new Fixture();
    fixture.startTurn();
    fixture.end();
    const sent: Record<string, unknown>[] = [];
    const session = recordingSession(fixture, sent);
    try {
      render(<LocaleProvider locale="en"><StoreProvider holder={fixture.holder} session={session}><Composer sessionId={SESSION} /></StoreProvider></LocaleProvider>);
      if (newQuestion) {
        const fresh = screen.getByRole("button", { name: "New question" });
        expect(fresh.getAttribute("aria-pressed")).toBe("false");
        fireEvent.click(fresh);
        expect(fresh.getAttribute("aria-pressed")).toBe("true");
        expect(screen.getByText("Your next message starts a new question.")).toBeTruthy();
      }
      const box = screen.getByRole("textbox", { name: "Message to the tutor" });
      fireEvent.paste(box, paste(text));
      fireEvent.keyDown(box, { key: "Enter" });
      await flush();
      return sent.at(-1);
    } finally {
      session.close();
      cleanup();
    }
  }

  test("test_ped01_new_question_is_sent_as_a_question", async () => {
    // With turns in the session, a line is an answer to the tutor's last question...
    expect(await composeAndSend("v = 10", false)).toMatchObject({ intent: "answer" });
    // ...and after "New question" the message starts another problem.
    expect(await composeAndSend("A ball is dropped from 20 m. How long does it fall?", true))
      .toMatchObject({ intent: "ask", content: [{ type: "text", text: "A ball is dropped from 20 m. How long does it fall?" }] });
  });

  test("the working board's photo action says it is for working", () => {
    const fixture = new Fixture();
    fixture.startTurn();
    fixture.end();
    render(<LocaleProvider locale="en"><StoreProvider holder={fixture.holder} session={null}><WorkingEntry sessionId={SESSION} /></StoreProvider></LocaleProvider>);
    expect(screen.queryByRole("button", { name: "Photo of a question" })).toBeNull();
    expect(screen.getByRole("button", { name: "Photo of my working" })).toBeTruthy();
  });
});

describe("DSN-12 and UXS-01", () => {
  test("test_dsn12_confirm_dialog_traps_focus_and_escape_cancels", async () => {
    const onCancel = vi.fn();
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const view = render(<ConfirmDialog open message="Delete Ada's profile?" confirm="Delete profile" cancel="Cancel" onConfirm={() => undefined} onCancel={onCancel} />);
    const dialog = screen.getByRole("alertdialog");
    const [cancel, confirm] = within(dialog).getAllByRole("button");
    expect(document.activeElement).toBe(cancel); // the safe action first
    confirm!.focus();
    fireEvent.keyDown(confirm!, { key: "Tab" });
    expect(document.activeElement).toBe(cancel); // Tab wraps inside the dialog
    fireEvent.keyDown(cancel!, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);
    fireEvent.keyDown(confirm!, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    view.rerender(<ConfirmDialog open={false} message="Delete Ada's profile?" confirm="Delete profile" cancel="Cancel" onConfirm={() => undefined} onCancel={onCancel} />);
    expect(document.activeElement).toBe(opener); // focus goes back where it was
    opener.remove();
  });

  test("test_uxs01_icon_button_shows_its_label", () => {
    render(<IconButton icon="settings" label="Settings" onClick={() => undefined} />);
    const button = screen.getByRole("button", { name: "Settings" });
    const shown = button.parentElement!.querySelector("[data-icon-label]")!;
    expect(shown.textContent).toBe("Settings");
    expect(shown.getAttribute("aria-hidden")).toBe("true"); // the name is read once, from the button
    expect(button.hasAttribute("title")).toBe(false);
  });
});

describe("UXS-23", () => {
  test("test_uxs23_finish_moves_focus_and_announces", () => {
    const lesson = (STATES.find((s) => s.id === "lesson-player.canonical")!.payload as { lesson: { blocks: unknown[] } & Record<string, unknown> }).lesson;
    const last = lesson.blocks.length - 1;
    const view = { status: "ready" as const, lessonId: String(lesson.lesson_id), lesson: lesson as never, index: last, checks: {}, positionFailed: false };
    render(<LocaleProvider locale="en"><LessonPlayerContent view={view} actions={{ onGo: () => undefined, onAnswer: () => undefined, onClose: () => undefined }} /></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    const message = screen.getByText("You've finished this lesson. Your answers are saved on this computer.");
    expect(document.activeElement).toBe(message);
    expect(message.closest("[role='status']")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(document.activeElement?.tagName).toBe("H2"); // back to the part's heading
  });
});

describe("UXS-44", () => {
  test("test_uxs44_report_saved_locally_and_listed_in_help", async () => {
    const fixture = new Fixture();
    const turnId = fixture.startTurn();
    fixture.end();
    const reports: Record<string, unknown>[] = [];
    const session = recordingSession(fixture, [], reports);
    try {
      render(<LocaleProvider locale="en"><StoreProvider holder={fixture.holder} session={session}><ReportProblem sessionId={SESSION} turnId={turnId} /></StoreProvider></LocaleProvider>);
      fireEvent.click(screen.getByRole("button", { name: "Report a problem" }));
      const sheet = screen.getByRole("group", { name: "What's the problem?" });
      expect(within(sheet).getAllByRole("radio").map((r) => r.parentElement?.textContent)).toEqual(["It isn't right", "It's confusing", "It's unsafe or upsetting"]);
      expect((screen.getByRole("checkbox", { name: "Let this report and note be sent to support" }) as HTMLInputElement).checked).toBe(false);
      fireEvent.click(within(sheet).getByRole("radio", { name: "It's unsafe or upsetting" }));
      expect(screen.getByText("If you feel unsafe, talk to an adult you trust.")).toBeTruthy();
      fireEvent.change(screen.getByRole("textbox", { name: /Note/ }), { target: { value: "The second step looked odd." } });
      fireEvent.click(screen.getByRole("button", { name: "Save report" }));
      await screen.findByText("Thanks. Your report is saved on this computer. You can send it to us from Settings, under Help.");
      expect(reports).toEqual([{ session_id: SESSION, turn_ids: [turnId], category: "unsafe", note: "The second step looked odd.", allow_support_export: false }]);
    } finally {
      session.close();
    }
  });

  test("help lists the open profile's reports and removes one", async () => {
    const core = new FakeProfileCore();
    const reports = [{ report_id: "1".repeat(26), session_id: SESSION, turn_ids: ["trn_x"], category: "confusing", note: "Step two", created_at: "2026-10-14T09:00:00.000Z", expires_at: "2027-10-14T09:00:00.000Z", allow_support_export: false }];
    const fetch = core.fetch;
    core.fetch = async (input, init = {}) => {
      const path = new URL(String(input)).pathname;
      if (path === "/v1/problem-reports") return new Response(JSON.stringify(reports));
      if (path.startsWith("/v1/problem-reports/") && init.method === "DELETE") {
        reports.splice(0, 1);
        return new Response(null, { status: 204 });
      }
      return fetch(input, init);
    };
    const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    await profiles.load();
    await profiles.unlock(PROFILES[0]!.profile_id);
    render(<LocaleProvider locale="en"><ProblemReportList profiles={profiles} /></LocaleProvider>);
    const item = (await screen.findByText("Step two")).closest<HTMLElement>("[data-report-id]")!;
    expect(item.textContent).toContain("It's confusing");
    expect(item.textContent).toContain("Step two");
    fireEvent.click(within(item).getByRole("button", { name: "Remove" }));
    await screen.findByText("No problem reports.");
  });
});
