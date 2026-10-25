import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import type { LessonView, SubjectMap } from "@jana/client-core";
import { STATES } from "@jana/ui/gallery";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

const MAP = (STATES.find((s) => s.id === "subject-map.canonical.topic-sheet")!.payload as { map: SubjectMap }).map;
const LESSON = (STATES.find((s) => s.id === "lesson-player.canonical")!.payload as { lesson: LessonView }).lesson;
const TOPIC = MAP.sections.flatMap((s) => s.topics).find((t) => t.lessons.some((l) => l.lesson_id === LESSON.lesson_id))!;
const KC = TOPIC.kcs.find((k) => LESSON.kc_ids.includes(k.kc_id))!;
afterEach(cleanup);

async function open() {
  const core = new FakeProfileCore();
  core.maps.set(MAP.subject_id, MAP);
  core.lessons.set(LESSON.lesson_id, LESSON as unknown as Record<string, unknown>);
  core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  core.practiceItems = LESSON.blocks.flatMap((b) => "items" in b ? b.items : []).slice(0, 3).map((item) => ({ ...item }));
  core.propose([{ kind: "main", kc_ids: [KC.kc_id], minutes: 20 }]);
  const runtime = createRuntime(core.launch, core.fetch);
  render(<App runtime={runtime} />);
  fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
  const plan = await screen.findByRole("region", { name: /^Next up/ });
  await waitFor(() => expect(plan.textContent).toContain(TOPIC.title));
  return { core, runtime, plan };
}

test("daily plan enters a saved objective, lesson tutoring returns to it, and Home resumes without restarting", async () => {
  const { core, runtime, plan } = await open();
  fireEvent.click(within(plan).getByRole("button", { name: "Start" }));
  await screen.findByRole("heading", { level: 1, name: LESSON.title });
  const goal = await screen.findByRole("region", { name: "Learning objective" });
  expect(goal.textContent).toContain(KC.statement);
  expect(core.log.find((r) => r.path === "/v1/learning-journey" && r.method === "POST")?.body).toMatchObject({ node_id: TOPIC.node_id, kc_id: KC.kc_id });
  expect(core.currentPlan()?.blocks[0]?.status).toBe("in_progress");
  fireEvent.click(screen.getByRole("button", { name: "Ask about this" }));
  const back = await screen.findAllByRole("button", { name: "Back to lesson" });
  fireEvent.click(back[0]!);
  await screen.findByRole("heading", { level: 1, name: LESSON.title });
  expect(runtime.lessons.getView().lesson?.lesson_id).toBe(LESSON.lesson_id);
  fireEvent.click(screen.getByRole("button", { name: "Back to daily plan" }));
  await screen.findByRole("heading", { name: /^Ready to learn, Ada/ });
  expect((await screen.findByRole("region", { name: /^Next up/ })).closest("details")?.open).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Continue the lesson" }));
  await screen.findByRole("heading", { level: 1, name: LESSON.title });
  expect(core.log.filter((r) => r.path === "/v1/learning-journey" && r.method === "POST")).toHaveLength(1);
});

test("practice help returns to the same saved question and keeps the answer draft", async () => {
  const { core, runtime, plan } = await open();
  fireEvent.click(within(plan).getByRole("button", { name: "Start" }));
  await screen.findByRole("heading", { level: 1, name: LESSON.title });
  fireEvent.click(screen.getByRole("button", { name: "Try a question" }));
  await screen.findByRole("heading", { level: 1, name: "Today's practice" });
  const setId = runtime.practice.getView().setId;
  const itemId = runtime.practice.getView().item?.item_id;
  fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "12.5" } });
  const draft = runtime.practice.getView().draft;
  fireEvent.click(screen.getByRole("button", { name: "Give me a hint" }));
  fireEvent.click(await screen.findByRole("button", { name: "Back to your question" }));
  await screen.findByRole("heading", { level: 1, name: "Today's practice" });
  expect(runtime.practice.getView()).toMatchObject({ setId, item: { item_id: itemId }, draft });
  expect((screen.getByLabelText("Your answer") as HTMLInputElement).value).toBe("12.5");
  expect(core.log.filter((r) => r.path === `/v1/practice/sets/${setId}` && r.method === "GET")).toHaveLength(1);
});
