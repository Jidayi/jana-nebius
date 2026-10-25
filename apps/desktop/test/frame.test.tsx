// UXS-01 in the app as it is wired: a profile opens on Home, the hub, which greets the student ("Ready to learn?") with the one input front
// and centre; the studio frame's sidebar lists the profile's recent sessions (`GET /v1/sessions`), a recent session
// reopens in the tutor where it was left, and "New question" starts a new session for the subject. Against the fake core.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { SubjectMap } from "@jana/client-core";
import { BASE } from "@jana/i18n";
import { STATES } from "@jana/ui/gallery";
import { S2_ROUTES } from "../src/routes.js";
import { FakeProfileCore, PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

const ADA = PROFILES[0]!;

// A wide window (the full sidebar, DSN-17); the test DOM's own window is narrower.
beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({
  matches: true, media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined,
  addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
})));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const pack = (subject: string) => ({ pack_id: `pack.${subject}.o`, subject, level: "O" as const, version: "0.1.0", signature_ok: true, size_bytes: 1 });

async function open(fake: FakeProfileCore) {
  render(<App runtime={createRuntime(fake.launch, fake.fetch)} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
  return screen.findByRole("navigation", { name: "Main" });
}

const posts = (fake: FakeProfileCore) => fake.log.filter((r) => r.method === "POST" && r.path === "/v1/sessions");

describe("UXS-01", () => {
  test("saved materials stay reachable while the tutor session is still opening", async () => {
    const fake = new FakeProfileCore();
    fake.packs.push(pack("phy"));
    const fetch = fake.fetch;
    fake.fetch = async (input, init) => {
      if (/\/v1\/sessions\/[^/]+\/snapshot$/.test(String(input))) return new Promise<Response>(() => undefined);
      const response = await fetch(input, init);
      if (String(input).endsWith("/v1/meta")) return Response.json({ ...await response.json(), capabilities: ["study_workspace"] });
      return response;
    };
    const nav = await open(fake);
    const materials = await within(nav).findByRole("button", { name: "My materials" });
    fireEvent.click(materials);
    await screen.findByRole("heading", { name: "Study", level: 1 });
    expect(fake.log.filter((r) => r.method === "DELETE")).toEqual([]);
  });

  test("personal learning comes before the grouped curriculum and preserves every existing destination", async () => {
    const fake = new FakeProfileCore();
    fake.packs.push(pack("phy"));
    const fetch = fake.fetch;
    fake.fetch = async (input, init) => {
      if (String(input).endsWith("/v1/meta")) {
        const response = await fetch(input, init);
        return Response.json({ ...await response.json(), capabilities: ["study_workspace"] });
      }
      return fetch(input, init);
    };
    const nav = await open(fake);
    await within(nav).findByRole("button", { name: "My materials" });
    const groups = within(nav).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["Your learning", "O-level curriculum"]);
    expect(within(groups[0]!).getAllByRole("button").map((b) => b.textContent)).toEqual(["My materials", "Progress", "Notes and saved"]);
    expect(within(groups[1]!).getAllByRole("button").map((b) => b.textContent)).toEqual(["Lessons", "Practice", "Mock exam"]);
    expect(within(nav).getByRole("button", { name: "New question" })).toBeTruthy();
    expect(within(nav).getByRole("region", { name: "Recent sessions" })).toBeTruthy();
    fireEvent.click(within(nav).getByRole("button", { name: "Progress" }));
    await waitFor(() => expect(document.querySelector("[data-app-screen]")?.getAttribute("data-app-screen")).toBe("progress"));
    fireEvent.click(within(nav).getByRole("button", { name: "Lessons" }));
    await waitFor(() => expect(document.querySelector("[data-app-screen]")?.getAttribute("data-app-screen")).toBe("learn"));
    expect(fake.log.filter((r) => r.method === "DELETE")).toEqual([]);
  });

  test("test_uxs01_recent_sessions_and_new_question", async () => {
    const fake = new FakeProfileCore();
    fake.packs.push(pack("phy"));
    const nav = await open(fake);
    // A profile opens on Home, the hub (UXS-01): the greeting and the Ask box.
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    expect(screen.getByRole("heading", { name: "Ask a question" })).toBeTruthy();
    expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBe("page");
    // The session the tutor would continue is listed under its day (the fake's sessions are old), not current on Home.
    const recent = within(nav).getByRole("region", { name: "Recent sessions" });
    const listed = await within(recent).findByRole("button", { name: new RegExp(ADA.canary) });
    expect(recent.textContent).toContain("Older");
    expect(listed.getAttribute("aria-current")).toBeNull();
    // A recent session reopens in the tutor, current while the tutor shows it.
    fireEvent.click(listed);
    await waitFor(() => expect(within(nav).getByRole("button", { name: new RegExp(ADA.canary) }).getAttribute("aria-current")).toBe("true"));
    // Back on Home it is no longer current.
    fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    expect(within(nav).getByRole("button", { name: new RegExp(ADA.canary) }).getAttribute("aria-current")).toBeNull();
    // New question starts a new session for the subject.
    const before = posts(fake).length;
    fireEvent.click(within(nav).getByRole("button", { name: "New question" }));
    await waitFor(() => expect(posts(fake)).toHaveLength(before + 1));
    expect(posts(fake).at(-1)?.body).toMatchObject({ subject: "physics", level: "O", mode: "guided" });
  });

  test("a question asked from Home's Ask box is not left in the tutor's composer", async () => {
    // Home's Ask box hands the question to the tutor (UXS-12): the tutor's composer opens empty, and Home's own box (its
    // own saved draft) is empty when the student comes back.
    const fake = new FakeProfileCore();
    fake.packs.push(pack("phy"));
    const nav = await open(fake);
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    const ask = await waitFor(() => {
      const box = document.querySelector<HTMLElement>("[contenteditable='true']");
      expect(box).not.toBeNull();
      return box!;
    });
    const question = "A ball is dropped from 20 m. How long does it fall?";
    fireEvent.paste(ask, { clipboardData: { getData: (type: string) => (type === "text/plain" ? question : "") } });
    await waitFor(() => expect(ask.textContent).toContain("A ball is dropped"));
    fireEvent.keyDown(ask, { key: "Enter" });
    // The tutor opens with the question sent and an empty composer.
    await waitFor(() => expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBeNull());
    await waitFor(() => expect(fake.log.some((r) => r.method === "GET" && r.path.endsWith("/drafts/ask"))).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));
    const composer = document.querySelector<HTMLElement>("[contenteditable='true']");
    expect(composer?.textContent ?? "").not.toContain("A ball is dropped");
    // Neither the tutor's saved draft nor Home's own holds the question once it was sent.
    await waitFor(() => expect(JSON.stringify([...fake.drafts.values()])).not.toContain("A ball is dropped"));
    expect([...fake.drafts.keys()].some((k) => k.endsWith(":home_ask"))).toBe(true);
    // Back on Home the Ask box is empty too: its saved draft was emptied when the question was sent.
    fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelector<HTMLElement>("[contenteditable='true']")?.textContent ?? "").not.toContain("A ball is dropped");
  });
});

// Crawl the declared paths by clicking the actual app, starting on Home for every route.
test.each(S2_ROUTES)("uxs01_two_click_reachability: $screen", async (route) => {
  expect(route.keys.length).toBeLessThanOrEqual(2);
  const fake = new FakeProfileCore();
  fake.packs.push(pack("phy"));
  const map = (STATES.find((s) => s.id === "subject-map.canonical.topic-sheet")!.payload as { map: SubjectMap }).map;
  const lesson = (STATES.find((s) => s.id === "lesson-player.canonical")!.payload as { lesson: Record<string, unknown> & { lesson_id: string } }).lesson;
  fake.maps.set(map.subject_id, map);
  fake.lessons.set(lesson.lesson_id, lesson);
  await open(fake);
  await waitFor(() => expect(document.querySelector("[data-app-screen]")?.getAttribute("data-app-screen")).toBe("home"));
  for (const key of route.keys) {
    // The student menu's row is named for the student; its items are menu items whose names start with their words.
    if (key === "frame.menu.label") {
      fireEvent.click(await waitFor(() => document.querySelector<HTMLElement>("[data-student-menu]")!));
      continue;
    }
    const label = key === "map.open_lesson" ? new RegExp("^Open lesson:") : BASE[key];
    expect(label).toBeDefined();
    const items = screen.queryAllByRole("menuitem", { name: new RegExp(`^${String(label).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) });
    const buttons = items.length > 0 ? items : await screen.findAllByRole("button", { name: label! });
    fireEvent.click(buttons[0]!);
  }
  await waitFor(() => expect(document.querySelector("[data-app-screen]")?.getAttribute("data-app-screen")).toBe(route.screen));
});
