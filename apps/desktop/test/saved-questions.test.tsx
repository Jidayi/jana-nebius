import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SAVED, savedCore } from "../../../packages/client-core/test/savedcore.js";
import { PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { menuItem } from "./student-menu.js";
beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("prefers-color-scheme"), media: query, addEventListener() {}, removeEventListener() {} })));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function open(name = "Ada") {
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^${name}`) }));
  const nav = await screen.findByRole("navigation", { name: "Main" });
  fireEvent.click(within(nav).getByRole("button", { name: "Notes and saved" }));
  fireEvent.click(await screen.findByRole("button", { name: "Saved questions" }));
}
test("saved questions survive restart, resolve and remove locally, and stay with their student", async () => {
  const fake = savedCore(); let runtime = createRuntime(fake.core.launch, fake.fetch);
  await runtime.profiles.load(); await runtime.profiles.unlock(PROFILES[0]!.profile_id);
  expect(await runtime.savedQuestions.save(SAVED.session_id, "trn_00000000000000000000000001")).toBe(true);
  await runtime.profiles.lock();
  runtime = createRuntime(fake.core.launch, fake.fetch); render(<App runtime={runtime} />); await open();
  fireEvent.click(await screen.findByRole("button", { name: SAVED.snapshot.problem }));
  await screen.findByText("Divide distance by time");
  fireEvent.click(screen.getByRole("button", { name: "Mark resolved" })); await screen.findByText("Resolved");
  fireEvent.click(menuItem("Switch student")); await open("Ben");
  await screen.findByText("Questions you save for later will appear here.");
  expect(screen.queryByText(SAVED.snapshot.problem)).toBeNull();
  fireEvent.click(menuItem("Switch student")); await open();
  fireEvent.click(await screen.findByRole("button", { name: SAVED.snapshot.problem }));
  fireEvent.click(screen.getByRole("button", { name: "Remove saved question" }));
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove saved question" }));
  await screen.findByText("Questions you save for later will appear here.");
  expect(fake.requests.map((r) => r.method)).toEqual(["POST", "PATCH", "DELETE"]);
});
