// UXS-33, TCH-14, UXS-48 and DSN-22 on screen and in print: the parent summary worded from the digest and printed alone
// in the print theme of tokens.json, the alerts by kind and date only, and the session history read-only with no
// sharing action. All data synthetic.
import fs from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { EMPTY_HISTORY, ParentController, ProfileController, StoreHolder } from "@jana/client-core";
import { ALERTS, DIGEST, HISTORY, OPENED, SESSION_KEPT, parentCore } from "../../client-core/test/parentcore.js";
import { PROFILES } from "../../client-core/test/profilecore.js";
import { TOKENS } from "../src/generated/tokens.js";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { SessionHistoryContent } from "../src/progress/SessionHistory.js";
import { AlertsContent, ParentSummary, ParentSummaryContent } from "../src/settings/ParentSummary.js";

afterEach(cleanup);

const ROOT = path.resolve(import.meta.dirname, "../../..");
const css = (file: string) => fs.readFileSync(path.join(import.meta.dirname, "..", file), "utf8");
const ready = { digestStatus: "ready" as const, digest: DIGEST };

describe("DSN-22", () => {
  test("test_dsn22_print_theme_from_tokens", () => {
    // The print theme is tokens.json's own, emitted as `--print-*` properties, and the report maps its roles onto it.
    const contract = JSON.parse(fs.readFileSync(path.join(ROOT, "packages/ui/tokens.json"), "utf8")).print;
    const tokens = css("src/generated/tokens.css");
    for (const [role, value] of Object.entries(contract.color as Record<string, string>)) expect(tokens).toContain(`--print-color-${role}: ${value};`);
    for (const [name, size] of Object.entries(contract.typeScalePt as Record<string, { size: number }>)) expect(tokens).toContain(`--print-text-${name}: ${size.size}pt;`);
    expect(TOKENS.print.page.marginMm).toBe(15);
    const sheet = css("src/styles/ui.css");
    const page = /@page report \{([\s\S]*?)\n\}/.exec(sheet)?.[1] ?? "";
    expect(page).toContain("size: A4 portrait;");
    expect(page).toContain(`margin: ${contract.page.marginMm}mm;`);
    expect(page).toMatch(/counter\(page\)[\s\S]*counter\(pages\)/);
    const report = /\[data-print-report\] \{([\s\S]*?)\n {2}\}/.exec(sheet)?.[1] ?? "";
    for (const role of ["ink", "muted", "line", "canvas"]) expect(report).toMatch(new RegExp(`--color-${role}: var\\(--print-color-`));
    for (const size of ["heading", "body", "meta", "label"]) expect(report).toContain(`--text-${size}: var(--print-text-`);
  });

  test("test_dsn22_report_header_and_mastery_words", () => {
    // Printing adds the report header (the product's name and the date generated) and drops the on-screen actions;
    // ideas carry their mastery pattern, icon and word, never colour alone (DSN-23).
    render(<LocaleProvider locale="en"><ParentSummaryContent view={ready} name="Ama" printing onRetry={() => undefined} /></LocaleProvider>);
    const header = document.querySelector("[data-print-header]")!;
    expect(header.querySelector("[data-brand]")).not.toBeNull();
    expect(header.textContent).toContain("Jana");
    expect(header.textContent).toMatch(/Made on \d{1,2} \w+ \d{4}/);
    expect(screen.queryByRole("button", { name: "Print or save as PDF" })).toBeNull();
    const marks = [...document.querySelectorAll("[data-print-report] [data-mastery]")];
    expect(marks.map((m) => [m.getAttribute("data-mastery"), m.textContent])).toEqual([["mastered", "Secure"], ["learning", "Learning"]]);
    expect(marks.every((m) => /mastery-pattern-/.test(m.className) && m.querySelector("svg") !== null)).toBe(true);
    cleanup();
    render(<LocaleProvider locale="en"><ParentSummaryContent view={ready} name="Ama" onRetry={() => undefined} /></LocaleProvider>);
    expect(document.querySelector("[data-print-header]")).toBeNull();
  });
});

describe("UXS-33", () => {
  test("test_uxs33_summary_renders_and_prints_offline", async () => {
    // With no network at all: the summary comes from the core on this computer, and printing it (the system's dialog,
    // which saves a PDF) sends nothing anywhere.
    const fake = parentCore();
    const dialled: string[] = [];
    const offline = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      if (!["127.0.0.1", "localhost", "core.test"].includes(url.hostname)) { dialled.push(url.hostname); throw new TypeError("offline"); }
      return fake.fetch(input, init);
    }) as typeof fetch;
    const profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: offline });
    await profiles.load();
    await profiles.unlock(PROFILES[0]!.profile_id);
    const print = vi.fn();
    const before = window.print;
    window.print = print;
    render(<LocaleProvider locale="en"><ParentSummary profiles={profiles} controller={new ParentController(profiles)} /></LocaleProvider>);
    await screen.findByText("This week Ada studied for 2 h 15 min across 4 days and secured 1 new idea in Physics.");
    expect(screen.getByText("Ask Ada to show you one thing about Inside the atom that still feels tricky.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Print or save as PDF" }));
    expect(print).toHaveBeenCalledOnce();
    window.dispatchEvent(new Event("beforeprint"));
    await waitFor(() => expect(document.querySelector("[data-print-header]")).not.toBeNull());
    expect(document.documentElement.style.getPropertyValue("--print-page-label")).toBe('"Page"');
    window.dispatchEvent(new Event("afterprint"));
    await waitFor(() => expect(document.querySelector("[data-print-header]")).toBeNull());
    expect(dialled).toEqual([]);
    window.print = before;
  });

  test("test_uxs33_empty_and_too_little", () => {
    render(<LocaleProvider locale="en"><ParentSummaryContent view={{ digestStatus: "ready", digest: { ...DIGEST, activity: "none" } }} name="Ama" onRetry={() => undefined} /></LocaleProvider>);
    expect(screen.getByText("No study sessions this week.")).toBeTruthy();
    expect(document.querySelector("table")).toBeNull();
    cleanup();
    render(<LocaleProvider locale="en"><ParentSummaryContent view={{ digestStatus: "ready", digest: { ...DIGEST, activity: "low", minutes_total: 12 } }} name="Ama" onRetry={() => undefined} /></LocaleProvider>);
    expect(screen.getByText("Not enough activity this week to summarise. Ama studied for 12 minutes.")).toBeTruthy();
    expect(screen.queryByText("Ideas secured")).toBeNull(); // time studied only (JRN-13 F1)
    expect(document.querySelectorAll("[data-parent-day]")).toHaveLength(7);
  });
});

describe("TCH-14", () => {
  test("test_tch14_alerts_kind_and_date_only", () => {
    const onDismiss = vi.fn();
    const view = { alertsStatus: "ready" as const, alerts: ALERTS, dismissing: null, dismissFailed: false };
    render(<LocaleProvider locale="en"><AlertsContent view={view} idea={() => "Motion"} onDismiss={onDismiss} onRetry={() => undefined} /></LocaleProvider>);
    const rows = [...document.querySelectorAll("[data-alert]")];
    expect(rows.map((r) => r.getAttribute("data-alert"))).toEqual(["mastery_drop", "wellbeing_message_shown", "mock_result"]);
    // The wellbeing alert says what kind it is and when: nothing the student wrote, no category beyond its kind.
    const wellbeing = rows[1]!;
    expect(wellbeing.textContent).toMatch(/^The tutor showed a wellbeing messagePlease check in · \d{1,2} \w+ \d{4}Put away$/);
    fireEvent.click(within(rows[0] as HTMLElement).getByRole("button", { name: "Put away" }));
    expect(onDismiss).toHaveBeenCalledWith(ALERTS[0]!.alert_id);
    cleanup();
    render(<LocaleProvider locale="en"><AlertsContent view={{ ...view, alerts: [] }} idea={() => null} onDismiss={onDismiss} onRetry={() => undefined} /></LocaleProvider>);
    expect(screen.getByText("No alerts.")).toBeTruthy();
  });
});

describe("UXS-48", () => {
  const actions = { onOpen: vi.fn(), onBack: vi.fn(), onClose: vi.fn(), onRetry: vi.fn(), onMore: vi.fn() };

  test("test_uxs48_history_read_only_without_sharing", () => {
    render(<LocaleProvider locale="en"><SessionHistoryContent view={{ ...EMPTY_HISTORY, status: "ready", sessions: HISTORY.sessions, retentionDays: 90 }} subject={() => "Physics"} actions={actions} /></LocaleProvider>);
    expect(screen.getByText("Conversations are kept on this computer for 90 days, then deleted. Your progress stays.")).toBeTruthy();
    expect(document.querySelector(`[data-history-session="${HISTORY.sessions[1]!.session_id}"]`)!.textContent).toContain("Conversation deleted, progress kept");
    fireEvent.click(screen.getByRole("button", { name: /Speed of a cyclist/ }));
    expect(actions.onOpen).toHaveBeenCalledWith(SESSION_KEPT);
    cleanup();
    const opening = { ...EMPTY_HISTORY, status: "ready" as const, sessions: HISTORY.sessions, retentionDays: 90, opened: { sessionId: SESSION_KEPT, status: "ready" as const, session: OPENED } };
    render(<LocaleProvider locale="en"><RegistryProvider registry={defaultRegistry()}><SessionHistoryContent view={opening} subject={() => "Physics"} actions={actions} /></RegistryProvider></LocaleProvider>);
    const opened = document.querySelector(`[data-history-opened="${SESSION_KEPT}"]`)!;
    expect(opened.textContent).toContain("A synthetic cyclist rides 20 m in 4 s. How fast?");
    expect(opened.textContent).toContain("Speed is distance over time.");
    // Read-only: nothing to share, send, export, report or save, and nowhere to type.
    const names = within(document.body).queryAllByRole("button").map((b) => b.textContent ?? b.getAttribute("aria-label") ?? "");
    expect(names.filter((n) => /share|send|export|teacher|report|save/i.test(n))).toEqual([]);
    expect(document.querySelector("textarea, [contenteditable='true']")).toBeNull();
  });
});
