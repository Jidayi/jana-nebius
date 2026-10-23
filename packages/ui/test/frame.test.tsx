// UXS-01 and DSN-17 (the studio frame: the sidebar's regions, the rail, the overlay drawer and the compact tab bar by
// breakpoint), UXS-14 (the board beside the conversation, closable, and a bottom sheet below 960 px whose toggle marks
// a change made while it was closed), UXS-12 (Home's sections) and LOC-12 (the frame's global keys, the keyboard help
// and the character keys the student can turn off).
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import type { DueIdea } from "@jana/client-core";
import { TOKENS } from "../src/generated/tokens.js";
import { Home, partOfDay } from "../src/home/Home.js";
import { LocaleProvider } from "../src/i18n.js";
import { ScreenHeader, Sidebar, StudioFrame, TabBar, type FramePlace, type SidebarContent } from "../src/frame/Frame.js";
import { layoutOf } from "../src/frame/layout.js";
import { useGlobalShortcuts } from "../src/frame/shortcuts.js";
import { KeyboardHelp, SHORTCUTS } from "../src/frame/KeyboardHelp.js";
import { TutorScreen } from "../src/TutorScreen.js";
import { Fixture, SESSION, id } from "./harness.js";

const BOARD = `brd_${"7".repeat(26)}`;
const original = window.matchMedia;

/** The window as `width` px wide, for the frame's media queries. */
function atWidth(width: number): void {
  window.matchMedia = ((query: string) => ({
    matches: width >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0), media: query, onchange: null,
    addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

beforeEach(() => atWidth(1440));
afterEach(() => {
  cleanup();
  window.matchMedia = original;
});

function places(onSelect: (id: string) => void = () => undefined): FramePlace[] {
  return [
    { id: "home", icon: "home", label: "Home", current: true, onSelect: () => onSelect("home") },
    { id: "learn", icon: "learn", label: "Learn", current: false, onSelect: () => onSelect("learn") },
  ];
}

function content(overrides: Partial<SidebarContent> = {}): SidebarContent {
  return {
    places: places(), onNewQuestion: () => undefined, onOpenSession: () => undefined, onSwitch: () => undefined, onSettings: () => undefined,
    settingsCurrent: false, profile: { name: "Ada", disc: 1 },
    sessions: [
      { group: "today", items: [{ id: "ses_a", title: "Ball thrown up", subject: "physics", subjectLabel: "Physics", current: true }] },
      { group: "yesterday", items: [{ id: "ses_b", title: "Moles in water", subject: "chemistry", subjectLabel: "Chemistry", current: false }] },
    ],
    ...overrides,
  };
}

function frame(sidebar: SidebarContent = content(), main = <p>Screen</p>) {
  return render(
    <LocaleProvider locale="en">
      <StudioFrame sidebar={({ variant, onToggle, onDone }) => <Sidebar variant={variant} onToggle={onToggle} onDone={onDone} content={sidebar} />} tabs={({ onMore }) => <TabBar places={sidebar.places} onMore={onMore} />}>
        {main}
      </StudioFrame>
    </LocaleProvider>,
  );
}

describe("UXS-01 and DSN-17", () => {
  test("test_uxs01_layout_classes_from_tokens", () => {
    const { medium, expanded, wide } = TOKENS.layout.breakpoints;
    expect([layoutOf(medium - 1), layoutOf(medium), layoutOf(expanded - 1), layoutOf(expanded), layoutOf(wide - 1), layoutOf(wide)])
      .toEqual(["compact", "medium", "medium", "expanded", "expanded", "wide"]);
  });

  test("test_uxs01_sidebar_regions", () => {
    const opened: string[] = [];
    frame(content({ onOpenSession: (sessionId) => opened.push(sessionId) }));
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav.getAttribute("data-variant")).toBe("full");
    // From the top: the mark, New question as the first row, the places with the current one marked, recent
    // sessions grouped by day, then the student, Switch student and Settings, named in words.
    expect(nav.querySelector("[data-brand='mark']")).not.toBeNull();
    expect(nav.querySelector("[data-brand='lockup']")).toBeNull();
    expect(within(nav).getByRole("button", { name: "New question" })).toBeTruthy();
    expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBe("page");
    const recent = within(nav).getByRole("region", { name: "Recent sessions" });
    expect([...recent.querySelectorAll("p")].map((p) => p.textContent)).toEqual(["Today", "Yesterday"]);
    fireEvent.click(within(recent).getByRole("button", { name: /^Moles in water/ }));
    expect(opened).toEqual(["ses_b"]);
    // The foot is one row, the student, opening their menu above it (D115): Settings and Switch student
    // are in it, named in words; Escape closes it and gives focus back to the row.
    const student = within(nav).getByRole("button", { name: "Ada, student menu" });
    expect(student.getAttribute("aria-haspopup")).toBe("menu");
    expect(within(nav).queryByRole("button", { name: "Switch student" })).toBeNull();
    fireEvent.click(student);
    const menu = within(nav).getByRole("menu", { name: "Ada, student menu" });
    expect(within(menu).getByRole("menuitem", { name: /^Settings/ })).toBeTruthy();
    expect(within(menu).getByRole("menuitem", { name: "Switch student" }).textContent).toBe("Switch student");
    expect(document.activeElement?.textContent).toMatch(/^Settings/);
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(within(nav).queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(student);
    // Collapsing gives the 72 px rail: icons with their words as names, the mark alone, no recent list.
    fireEvent.click(within(nav).getByRole("button", { name: "Collapse the sidebar" }));
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(rail.getAttribute("data-variant")).toBe("rail");
    expect(rail.querySelector("[data-brand='mark']")).not.toBeNull();
    expect(within(rail).queryByRole("region", { name: "Recent sessions" })).toBeNull();
    expect(within(rail).getByRole("button", { name: "Learn" })).toBeTruthy();
    expect(within(rail).getByRole("button", { name: "Expand the sidebar" })).toBeTruthy();
    // On the rail the avatar alone opens the same menu.
    fireEvent.click(within(rail).getByRole("button", { name: "Ada, student menu" }));
    expect(within(rail).getByRole("menuitem", { name: "Switch student" })).toBeTruthy();
  });

  test("test_uxs01_frame_by_breakpoint", () => {
    // Expanded: the sidebar starts as the rail.
    atWidth(1100);
    frame();
    expect(screen.getByRole("navigation", { name: "Main" }).getAttribute("data-variant")).toBe("rail");
    cleanup();

    // Medium: no sidebar on screen; the header's menu opens it as a modal drawer over a scrim; Escape closes it.
    atWidth(800);
    const { getByRole, queryByRole } = frame(content(), <HeaderOnly />);
    expect(queryByRole("navigation")).toBeNull();
    fireEvent.click(getByRole("button", { name: "Open the menu" }));
    const drawer = getByRole("dialog", { name: "Menu" });
    expect(within(drawer).getByRole("navigation", { name: "Main" }).getAttribute("data-variant")).toBe("drawer");
    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(queryByRole("dialog", { name: "Menu" })).toBeNull();
    // Choosing a place in the drawer closes it.
    fireEvent.click(getByRole("button", { name: "Open the menu" }));
    fireEvent.click(within(getByRole("dialog", { name: "Menu" })).getByRole("button", { name: "Learn" }));
    expect(queryByRole("dialog", { name: "Menu" })).toBeNull();
    cleanup();

    // Compact: a bottom tab bar replaces the sidebar; More opens the drawer.
    atWidth(400);
    frame();
    const tabs = screen.getByRole("navigation", { name: "Main" });
    expect(tabs.getAttribute("data-region")).toBe("tabs");
    expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual(["Home", "Learn", "More"]);
    fireEvent.click(within(tabs).getByRole("button", { name: "More" }));
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeTruthy();
  });

  test("test_uxs01_no_new_question_without_a_tutor", () => {
    const { onNewQuestion: _, ...rest } = content();
    frame(rest);
    expect(within(screen.getByRole("navigation", { name: "Main" })).queryByRole("button", { name: "New question" })).toBeNull();
  });
});

/** A screen with the shared header, as Home and the tutor have. */
function HeaderOnly() {
  return <ScreenHeader />;
}

function boardStep(f: Fixture, i: number, status: string) {
  f.emit({ type: "board.step", board_id: BOARD, step_id: `stp_${String(i).padStart(26, "0")}`, index: i, latex: `x = ${i}`, reason: null, owner: "student", status, check_id: null, error: null }, null);
}

function workspace(f: Fixture) {
  return f.render(
    <StudioFrame sidebar={({ variant, onToggle, onDone }) => <Sidebar variant={variant} onToggle={onToggle} onDone={onDone} content={content()} />}>
      <TutorScreen sessionId={SESSION} />
    </StudioFrame>,
  );
}

describe("UXS-14", () => {
  test("test_uxs14_board_panel_beside_and_closable", () => {
    const f = new Fixture();
    workspace(f);
    // No board until the tutor works a problem on it; then it opens beside the conversation.
    expect(document.querySelector("[data-board-panel]")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Show the board" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    f.emit({ type: "board.knowns", board_id: BOARD, knowns: [{ known_id: "kn_u", symbol: "u", label: "starting speed", value: "14", unit: "m/s", source: "question", check_id: null }], unknowns: [{ symbol: "s", label: "height", unit: "m" }], conventions: [] }, null);
    boardStep(f, 0, "correct");
    const panel = document.querySelector<HTMLElement>("[data-board-panel]")!;
    expect(panel).not.toBeNull();
    expect(within(panel).getByText("Given")).toBeTruthy();
    expect(within(panel).getByText("Find")).toBeTruthy();
    // The student closes it, from its header or the header's toggle, and shows it again with Ctrl+Shift+B.
    fireEvent.click(within(panel).getByRole("button", { name: "Close the board" }));
    expect(document.querySelector("[data-board-panel]")).toBeNull();
    fireEvent.keyDown(window, { key: "B", code: "KeyB", ctrlKey: true, shiftKey: true });
    expect(document.querySelector("[data-board-panel]")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Hide the board" }));
    expect(document.querySelector("[data-board-panel]")).toBeNull();
    // The conversation keeps its column and the composer stays docked under it.
    expect(screen.getByRole("log", { name: "Conversation" })).toBeTruthy();
    expect(document.querySelector("[data-region='dock'] [data-composer]")).not.toBeNull();
  });

  test("test_uxs14_knowns_named_in_words_read_as_text_with_one_unit", () => {
    const f = new Fixture();
    workspace(f);
    f.emit({ type: "board.knowns", board_id: BOARD, knowns: [
      { known_id: "kn_u", symbol: "initial_velocity", label: "starting speed", value: "14 m/s", unit: "m/s", source: "question", check_id: null },
      { known_id: "kn_g", symbol: "g", label: "gravity", value: "9.8", unit: "m/s^2", source: "question", check_id: null },
    ], unknowns: [{ symbol: "velocity after 2s (m/s)", label: "velocity", unit: "m/s" }], conventions: [] }, null);
    boardStep(f, 0, "correct");
    const knowns = document.querySelector<HTMLElement>("[data-knowns]")!;
    // A named quantity is words (not an italic run of letters), and a unit already in the value is not repeated.
    expect(within(knowns).getByText("initial velocity")).toBeTruthy();
    expect(within(knowns).getByText("14 m/s")).toBeTruthy();
    expect(within(knowns).queryByText("m/s")).toBeNull();
    expect(within(knowns).getByText("velocity after 2s (m/s)")).toBeTruthy();
    expect(within(knowns).getByText("m/s\u00b2")).toBeTruthy();
  });

  test("uxs14_board_sheet_below_breakpoint", () => {
    atWidth(TOKENS.layout.breakpoints.expanded - 1);
    const f = new Fixture();
    workspace(f);
    boardStep(f, 0, "awaiting");
    // Below 960 px the board does not take the conversation's room on its own: it opens as a bottom sheet.
    expect(document.querySelector("[data-board-sheet]")).toBeNull();
    const toggle = () => screen.getByRole("button", { name: /^(Show|Hide) the board/ });
    // What arrived while it was closed is marked on the toggle.
    expect(document.querySelector("[data-board-changed]")).not.toBeNull();
    fireEvent.click(toggle());
    expect(document.querySelector("[data-board-changed]")).toBeNull();
    const sheet = document.querySelector<HTMLElement>("[data-board-sheet]")!;
    expect(sheet).not.toBeNull();
    expect(sheet.className).toContain("rounded-t-sheet");
    expect(document.querySelector("[data-board-panel]")).toBeNull();
    fireEvent.click(within(sheet).getByRole("button", { name: "Close the board" }));
    // A change while the sheet is closed puts a dot on the toggle and says so in its name.
    boardStep(f, 0, "correct");
    expect(document.querySelector("[data-board-changed]")).not.toBeNull();
    expect(toggle().getAttribute("aria-label")).toBe("Show the board. It changed while it was closed.");
    fireEvent.click(toggle());
    expect(document.querySelector("[data-board-changed]")).toBeNull();
  });

  test("test_uxs14_header_names_the_session", () => {
    const f = new Fixture();
    workspace(f);
    const header = document.querySelector("header")!;
    expect(within(header).getByRole("heading", { level: 1 }).textContent).toBe("New question");
    expect(header.textContent).toContain("Physics");
    expect(header.querySelector("[data-mode='guided']")?.textContent).toBe("Mode: Guided");
    f.emit({ type: "session.updated", session_id: SESSION, title: "Ball thrown up at 14 m/s" }, null);
    expect(within(header).getByRole("heading", { level: 1 }).textContent).toBe("Ball thrown up at 14 m/s");
    // While a hint is open its rung shows in the header.
    const turn = f.startTurn();
    const part = id("prt");
    f.emit({ type: "part.start", part_id: part, kind: "card", index: 0 });
    f.emit({ type: "card.open", request_id: id("req"), part_id: part, call_id: null, card: { card_type: "hint", rung: 2, of: 5, body: "Which way does gravity pull?", actions: ["try_it", "next_hint", "show_step"] } });
    expect(turn).not.toBeNull();
    expect(within(header).getByText("Hint 2 of 5")).toBeTruthy();
  });
});

function Keys({ log }: { log: string[] }) {
  useGlobalShortcuts({ places: [() => log.push("home"), () => log.push("learn"), null, null, null], onSettings: () => log.push("settings") });
  return null;
}

describe("LOC-12", () => {
  test("test_loc12_global_shortcuts", () => {
    const log: string[] = [];
    const f = new Fixture();
    f.render(<>
      <Keys log={log} />
      <StudioFrame sidebar={({ variant, onToggle, onDone }) => <Sidebar variant={variant} onToggle={onToggle} onDone={onDone} content={content()} />}>
        <TutorScreen sessionId={SESSION} />
      </StudioFrame>
    </>);
    fireEvent.keyDown(window, { key: "1", code: "Digit1", ctrlKey: true });
    fireEvent.keyDown(window, { key: "2", code: "Digit2", metaKey: true }); // Cmd on macOS
    fireEvent.keyDown(window, { key: "3", code: "Digit3", ctrlKey: true }); // Practice is not on this build
    fireEvent.keyDown(window, { key: ",", code: "Comma", ctrlKey: true });
    expect(log).toEqual(["home", "learn", "settings"]);
    // F6 moves between the regions in order: sidebar, conversation, dock; Shift+F6 goes back.
    const sidebar = document.querySelector<HTMLElement>("[data-region='sidebar']")!;
    sidebar.focus();
    fireEvent.keyDown(window, { key: "F6" });
    expect(document.activeElement?.getAttribute("data-region")).toBe("conversation");
    fireEvent.keyDown(window, { key: "F6" });
    expect(document.activeElement?.closest("[data-region]")?.getAttribute("data-region")).toBe("dock");
    fireEvent.keyDown(window, { key: "F6", shiftKey: true });
    expect(document.activeElement?.getAttribute("data-region")).toBe("conversation");
    // "/" puts the cursor in the Ask box, but never while the student is typing in a field.
    const field = document.createElement("input");
    document.body.append(field);
    field.focus();
    fireEvent.keyDown(field, { key: "/" });
    expect(document.activeElement).toBe(field);
    field.remove();
    sidebar.focus();
    fireEvent.keyDown(sidebar, { key: "/" });
    expect(document.activeElement?.closest("[data-composer]")).not.toBeNull();
  });
});

function HelpKeys({ log, characterKeys }: { log: string[]; characterKeys: boolean }) {
  const [open, setOpen] = useState(false);
  useGlobalShortcuts({ places: [], onSettings: () => undefined, onHelp: () => { log.push("help"); setOpen(true); }, characterKeys });
  return <KeyboardHelp open={open} onClose={() => setOpen(false)} characterKeys={characterKeys} />;
}

describe("LOC-12 character keys", () => {
  test("loc12_character_key_shortcuts", () => {
    const log: string[] = [];
    const view = render(<LocaleProvider locale="en"><HelpKeys log={log} characterKeys /><div data-composer=""><textarea aria-label="Ask" /></div><input aria-label="Name" /></LocaleProvider>);
    // While the student types, "?" and "/" are just characters.
    const name = screen.getByRole("textbox", { name: "Name" });
    name.focus();
    fireEvent.keyDown(name, { key: "?" });
    fireEvent.keyDown(name, { key: "/" });
    expect(log).toEqual([]);
    expect(document.activeElement).toBe(name);
    // Out of a field, "?" opens the keyboard help: the shortcuts of TABLE LOC-12a this build has, each key drawn as a key.
    name.blur();
    fireEvent.keyDown(document.body, { key: "?" });
    expect(log).toEqual(["help"]);
    const help = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(within(help).getByRole("heading", { name: "Everywhere" })).toBeTruthy();
    for (const row of SHORTCUTS) expect(help.querySelector(`[data-shortcut="${row.action}"] kbd`), row.action).not.toBeNull();
    // Escape closes it.
    fireEvent.keyDown(help, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    // Turned off in Settings, neither "?" nor "/" does anything; the help says they are off.
    view.unmount();
    render(<LocaleProvider locale="en"><HelpKeys log={log} characterKeys={false} /><div data-composer=""><textarea aria-label="Ask" /></div></LocaleProvider>);
    fireEvent.keyDown(document.body, { key: "?" });
    fireEvent.keyDown(document.body, { key: "/" });
    expect(log).toEqual(["help"]);
    expect(document.activeElement).toBe(document.body);
  });
});

describe("UXS-12", () => {
  test("test_uxs12_home_sections", () => {
    const opened: string[] = [];
    const chosen: string[] = [];
    const practised: string[] = [];
    const idea = (kc: string, state: DueIdea["kc"]["state"]): DueIdea => ({ kc: { kc_id: kc, code: kc, statement: `Idea ${kc}`, state, band: "learning" }, subjectId: "cur.chm.o", subject: "chemistry", topicId: "top" });
    render(
      <LocaleProvider locale="en">
        <Home
          name="Ada"
          ask={<textarea aria-label="Message to the tutor" />}
          subjects={[
            { subjectId: "cur.phy.o", subject: "physics", label: "Physics", chosen: true },
            { subjectId: "cur.chm.o", subject: "chemistry", label: "Chemistry", chosen: false },
          ]}
          onSubject={(s) => chosen.push(s)}
          pickup={[
            { sessionId: "ses_a", title: "Ball thrown up", subject: "physics", subjectLabel: "Physics", day: "today" },
            { sessionId: "ses_b", title: "Moles", subject: "chemistry", subjectLabel: "Chemistry", day: "yesterday" },
            { sessionId: "ses_c", title: "Older one", subject: "chemistry", subjectLabel: "Chemistry", day: "older" },
          ]}
          onPickup={(s) => opened.push(s)}
          practice={{ ideas: [idea("kc1", "needs_review"), idea("kc2", "learning")], refreshes: 1, subjectLabel: (s) => (s === "chemistry" ? "Chemistry" : s) }}
          onPractice={(i) => practised.push(i.kc.kc_id)}
        />
      </LocaleProvider>,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Ready to learn, Ada?");
    expect(screen.getByRole("heading", { name: "Ask a question" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Message to the tutor" })).toBeTruthy();
    const group = screen.getByRole("group", { name: "Choose a subject" });
    expect(within(group).getByRole("button", { name: "Physics" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(group).getByRole("button", { name: "Chemistry" }));
    expect(chosen).toEqual(["cur.chm.o"]);
    // Pick up where you left off: the newest sessions, as many as the key allows, each reopening its session.
    const pickup = screen.getByRole("region", { name: "Pick up where you left off" });
    expect(within(pickup).getAllByRole("button")).toHaveLength(2);
    expect(pickup.textContent).toContain("Physics · Today");
    fireEvent.click(within(pickup).getByRole("button", { name: /Moles/ }));
    expect(opened).toEqual(["ses_b"]);
    // Today's practice: due ideas with their mastery word, never colour alone.
    const practice = screen.getByRole("region", { name: "Today's practice" });
    expect(practice.textContent).toContain("1 idea is due for a refresh");
    expect(practice.querySelector("[data-mastery='needs_review']")?.textContent).not.toBe("");
    fireEvent.click(within(practice).getByRole("button", { name: /Idea kc2/ }));
    expect(practised).toEqual(["kc2"]);
    expect([partOfDay(8), partOfDay(13), partOfDay(21)]).toEqual(["morning", "afternoon", "evening"]);
  });
});

