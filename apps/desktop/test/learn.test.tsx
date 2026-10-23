// UXS-22 and UXS-23 in the app as it is wired: Learn opens the subject map of the subjects on this computer, a tile's
// sheet starts its lesson and the lesson returns to the map; a mastery change on the open session re-reads the map; and
// asking from a topic or a lesson opens the tutor on that subject and topic. First run and the content-only class are
// in first-run.test.tsx. Against the fake core, with the gallery's fixtures (built from the repository's curriculum
// sources).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import type { SubjectMap as Map } from "@jana/client-core";
import { STATES } from "@jana/ui/gallery";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

const payload = <T,>(id: string) => STATES.find((s) => s.id === id)!.payload as T;
const MAP = payload<{ map: Map }>("subject-map.canonical.topic-sheet").map;
const LESSON = payload<{ lesson: Record<string, unknown> & { lesson_id: string } }>("lesson-player.canonical").lesson;
const TOPIC = MAP.sections[0]!.topics[0]!;

afterEach(() => cleanup());

async function open(setup: (core: FakeProfileCore) => void = () => undefined) {
  const core = new FakeProfileCore();
  core.maps.set(MAP.subject_id, MAP);
  core.lessons.set(LESSON.lesson_id, LESSON);
  core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  setup(core);
  const sessions: Record<string, unknown>[] = [];
  const fetch = core.fetch;
  core.fetch = async (input, init = {}) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.endsWith("/v1/sessions") && init.method === "POST" && typeof init.body === "string") {
      sessions.push(JSON.parse(init.body) as Record<string, unknown>);
    }
    return fetch(input, init);
  };
  const runtime = createRuntime(core.launch, core.fetch);
  render(<App runtime={runtime} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ })); // Ada has no PIN
  return { core, runtime, sessions };
}

describe("UXS-22 and UXS-23", () => {
  test("ask_uses_the_selected_subject_and_topic", async () => {
    const chemistry = JSON.parse(JSON.stringify(MAP).replaceAll(".phy.", ".chm.")) as Map;
    chemistry.subject = "chemistry";
    chemistry.title = "Chemistry";
    const { sessions } = await open((core) => {
      core.maps.set(chemistry.subject_id, chemistry);
      core.packs.push({ pack_id: "pack.chm.o", subject: "chm", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
    });
    const nav = await screen.findByRole("navigation", { name: "Main" });
    fireEvent.click(within(nav).getByRole("button", { name: "Learn" }));
    fireEvent.click(await screen.findByRole("radio", { name: "Chemistry" })); // the subject switch in Learn's header
    const topic = chemistry.sections[0]!.topics[0]!;
    const tile = await waitFor(() => {
      const found = document.querySelector<HTMLButtonElement>(`[data-topic-id="${topic.node_id}"]`);
      expect(found).not.toBeNull();
      return found!;
    });
    fireEvent.click(tile);
    const sheet = await screen.findByRole("dialog", { name: topic.title });
    fireEvent.click(within(sheet).getByRole("button", { name: "Ask the tutor about this" }));
    await waitFor(() => expect(sessions.at(-1)).toMatchObject({
      subject: "chemistry", level: "O", topic_id: topic.node_id, origin: { kind: "ask", ref: topic.node_id },
    }));
  });

  test("ask_from_a_lesson_carries_its_origin_and_topic", async () => {
    const { sessions } = await open();
    const nav = await screen.findByRole("navigation", { name: "Main" });
    fireEvent.click(within(nav).getByRole("button", { name: "Learn" }));
    const tile = await waitFor(() => {
      const found = document.querySelector<HTMLButtonElement>(`[data-topic-id="${TOPIC.node_id}"]`);
      expect(found).not.toBeNull();
      return found!;
    });
    fireEvent.click(tile);
    const sheet = await screen.findByRole("dialog", { name: TOPIC.title });
    fireEvent.click(within(sheet).getByRole("button", { name: /Start the lesson/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Ask about this" }));
    await waitFor(() => expect(sessions.at(-1)).toMatchObject({
      subject: "physics", topic_id: LESSON.node_id, origin: { kind: "lesson", ref: LESSON.lesson_id },
    }));
  });

  test("learn_opens_the_map_and_its_lessons", async () => {
    const { runtime } = await open();
    const nav = await screen.findByRole("navigation", { name: "Main" });
    fireEvent.click(within(nav).getByRole("button", { name: "Learn" }));
    const tile = await waitFor(() => {
      const found = document.querySelector<HTMLButtonElement>(`[data-topic-id="${TOPIC.node_id}"]`);
      expect(found).not.toBeNull();
      return found!;
    });
    expect(within(nav).getByRole("button", { name: "Learn" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(tile);
    const sheet = await screen.findByRole("dialog", { name: TOPIC.title });
    // A tutor answers on this computer: the sheet offers to ask it.
    expect(within(sheet).getByRole("button", { name: "Ask the tutor about this" })).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: /Start the lesson/ }));
    await screen.findByRole("heading", { level: 1, name: String(LESSON.title) });
    expect(screen.getByRole("button", { name: "Ask about this" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back to the map" }));
    await screen.findByRole("heading", { level: 1, name: String(MAP.title) });
    expect(runtime.lessons.getView().lesson?.lesson_id).toBe(LESSON.lesson_id);
    // The lesson part way through is offered above the topics; Continue opens it where it was.
    const progress = await screen.findByRole("region", { name: String(LESSON.title) });
    expect(progress.textContent).toContain("Lesson in progress");
    expect(within(progress).getByRole("progressbar", { name: "Lesson parts" }).getAttribute("aria-valuetext")).toMatch(/^Part 1 of \d+$/);
    fireEvent.click(within(progress).getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { level: 1, name: String(LESSON.title) });
  });
});
