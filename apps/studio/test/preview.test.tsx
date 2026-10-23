import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { STATES } from "@jana/ui/gallery";
import { Preview } from "../src/App.js";
import type { Json } from "../src/model.js";

afterEach(cleanup);
test("the studio renders the production lesson player and its canonical worked-example board", () => {
  const state = STATES.find((row) => row.id === "lesson-player.canonical.worked-example");
  expect(state).toBeDefined();
  const { lesson } = state!.payload as { lesson: Json };
  render(<Preview report={{ ok: true, problems: [], preview: { lesson } }} record={{ id: "synthetic-lesson" }} />);
  expect(screen.getByRole("button", { name: /next/i })).toBeTruthy();
});

test("aut13_board_preview_identical: Studio passes the same board data and markup as the learner renderer", async () => {
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { ExampleBoard, LocaleProvider } = await import("@jana/ui");
  const state = STATES.find((row) => row.id === "lesson-player.canonical.worked-example")!;
  const lesson = (state.payload as unknown as { lesson: import("@jana/client-core").LessonView }).lesson;
  const block = lesson.blocks.find((row) => row.type === "worked_example")!;
  if (block.type !== "worked_example") throw new Error("Missing board fixture");
  const example = block.worked_example;
  const studio = renderToStaticMarkup(<LocaleProvider locale="en"><Preview record={{ id: example.worked_example_id }} report={{ ok: true, problems: [], preview: { example: example as unknown as Json } }} /></LocaleProvider>);
  const learner = renderToStaticMarkup(<LocaleProvider locale="en"><ExampleBoard example={example} /></LocaleProvider>);
  expect(studio).toBe(learner);
  expect(studio).toContain("data-faded");
});

test("uxs37_preview_matches_student: authored-item preview uses identical lesson-player output", async () => {
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { LessonPlayerContent, LocaleProvider } = await import("@jana/ui");
  const state = STATES.find((row) => row.id === "lesson-player.canonical.worked-example")!;
  const lesson = (state.payload as unknown as { lesson: import("@jana/client-core").LessonView }).lesson;
  const studio = renderToStaticMarkup(<LocaleProvider locale="en"><Preview record={{ id: "itm.fixture" }} report={{ ok: true, problems: [], preview: { lesson: lesson as unknown as Json } }} /></LocaleProvider>);
  const learner = renderToStaticMarkup(<LocaleProvider locale="en"><LessonPlayerContent view={{ status: "ready", lessonId: lesson.lesson_id, lesson, index: 0, checks: {}, positionFailed: false }} actions={{ onGo: () => undefined, onAnswer: () => undefined }} /></LocaleProvider>);
  expect(studio).toBe(learner);
});
