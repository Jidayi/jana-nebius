import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { assessment, assessmentCore } from "../../../packages/client-core/test/assessmentcore.js";
import { PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("prefers-color-scheme"), media: query, addEventListener() {}, removeEventListener() {} })));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function setup() {
  const fake = assessmentCore();
  fake.core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  fake.core.models = { ...fake.core.models, installed: [] };
  fake.core.health = { status: "ok", components: { core: "ok", runtime: "down" }, readiness: "core_ready" };
  return fake;
}
async function unlock() {
  fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Home" }));
}
test("uxs40_finish_later_resumes", async () => {
  const fake = setup(); let runtime = createRuntime(fake.core.launch, fake.fetch);
  render(<App runtime={runtime} />); await unlock();
  fireEvent.click(await screen.findByRole("button", { name: "Find my starting point" }));
  await screen.findByText("This isn't a test. It helps me find the best place to start. Skip anything you haven't learned yet.");
  fireEvent.click(screen.getByRole("button", { name: "Start" }));
  await screen.findByText("Synthetic question 1");
  fireEvent.click(screen.getByRole("button", { name: "I haven't learned this yet" }));
  await screen.findByText("Synthetic question 2");
  fireEvent.click(screen.getByRole("button", { name: "Finish later" }));
  await screen.findByRole("button", { name: "Continue the check" });
  expect(fake.rows.get(PROFILES[0]!.profile_id)?.[0]?.answered_count).toBe(1);
  cleanup(); await runtime.profiles.lock();
  runtime = createRuntime(fake.core.launch, fake.fetch); render(<App runtime={runtime} />); await unlock();
  fireEvent.click(await screen.findByRole("button", { name: "Finish your check" }));
  fireEvent.click(await screen.findByRole("button", { name: "Find my starting point · Physics" }));
  fireEvent.click(await screen.findByRole("button", { name: "Continue the check" }));
  await screen.findByText("Synthetic question 2");
  expect(screen.getByRole("status").textContent).toContain("Picked up where you left off, at question 2.");
  expect(fake.writes.filter((r) => r.path === "/v1/assessments")).toHaveLength(1);
});
test("an open mastery check removes tutor routes and Alt+H cannot open help", async () => {
  const fake = setup(); fake.rows.set(PROFILES[0]!.profile_id, [assessment("mastery_check")]);
  const runtime = createRuntime(fake.core.launch, fake.fetch); render(<App runtime={runtime} />); await unlock();
  fireEvent.click(await screen.findByRole("button", { name: "Finish your check" }));
  fireEvent.click(await screen.findByRole("button", { name: "Mastery check · Physics" }));
  await screen.findByText("Synthetic question 1");
  expect(screen.queryByRole("button", { name: "New question" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Help me" })).toBeNull();
  fireEvent.keyDown(document, { key: "h", altKey: true });
  await waitFor(() => expect(document.querySelector("[contenteditable=true]")).toBeNull());
  expect(fake.core.log.filter((r) => r.path.endsWith("/turns"))).toHaveLength(0);
});
test("the mock lock prevents starting an assessment through Home or Progress", async () => {
  const fake = setup(); const runtime = createRuntime(fake.core.launch, fake.fetch);
  render(<App runtime={runtime} />); await unlock();
  // The controller's cached sitting is the same public lock consumed by keyboard and pointer routes.
  const mocks = runtime.mocks.getView();
  expect(mocks.status).toBe("ready");
  fake.fail("tutor_locked");
  fireEvent.click(await screen.findByRole("button", { name: "Find my starting point" }));
  fireEvent.click(await screen.findByRole("button", { name: "Start" }));
  await screen.findByText("Checks wait until your mock exam is submitted.");
  expect(fake.rows.get(PROFILES[0]!.profile_id)).toHaveLength(0);
});

test.each([
  ["mathematics", "mth", "Mathematics"], ["physics", "phy", "Physics"],
  ["chemistry", "chm", "Chemistry"], ["accounting", "acc", "Accounting"],
] as const)("three %s mastery answers release the tutor and a newly available question restores the lock", async (subject, code, label) => {
  const fake = assessmentCore();
  fake.core.packs.push({ pack_id: `pack.${code}.o`, subject: code, level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  fake.rows.set(PROFILES[0]!.profile_id, [assessment("mastery_check", 0, subject)]);
  const runtime = createRuntime(fake.core.launch, fake.fetch);
  render(<App runtime={runtime} />); await unlock();
  fireEvent.click(await screen.findByRole("button", { name: "Finish your check" }));
  fireEvent.click(await screen.findByRole("button", { name: `Mastery check · ${label}` }));
  for (const number of [1, 2]) {
    await screen.findByText(`Synthetic question ${number}`);
    expect(document.querySelector("[contenteditable=true]")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "First option" }));
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
  }
  await screen.findByRole("button", { name: "Check availability" });
  expect(fake.rows.get(PROFILES[0]!.profile_id)?.[0]?.state).toBe("waiting");
  // The server, rather than the client, decides when the spaced item is due.
  fake.rows.set(PROFILES[0]!.profile_id, [assessment("mastery_check", 2, subject)]);
  fireEvent.click(screen.getByRole("button", { name: "Check availability" }));
  await screen.findByText("Synthetic question 3");
  fireEvent.click(screen.getByRole("button", { name: "Home" }));
  await waitFor(() => expect(document.querySelector("[contenteditable=true]")).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "Finish your check" }));
  await screen.findByText("Synthetic question 3");
  fireEvent.click(screen.getByRole("radio", { name: "First option" }));
  fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
  await screen.findByText(/Nearly secure to Secure/);
  expect(fake.rows.get(PROFILES[0]!.profile_id)?.[0]).toMatchObject({ state: "completed", answered_count: 3, current_item: null });
  expect(fake.writes.filter((r) => r.path.endsWith("/answers"))).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: "Home" }));
  await waitFor(() => expect(document.querySelector("[contenteditable=true]")).not.toBeNull());
  expect(screen.getByRole("heading", { name: "Ask a question" })).toBeTruthy();
  const completed = fake.rows.get(PROFILES[0]!.profile_id)![0]!;
  const pending = { ...assessment("mastery_check", 0, subject), assessment_id: "00000000000000000000000091", state: "waiting" as const, current_item: null };
  fake.rows.set(PROFILES[0]!.profile_id, [completed, pending]);
  await act(() => runtime.assessments.load());
  expect(document.querySelector("[contenteditable=true]")).not.toBeNull();
  expect(screen.getByRole("heading", { name: "Ask a question" })).toBeTruthy();
});
