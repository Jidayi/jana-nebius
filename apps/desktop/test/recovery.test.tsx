import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { menuItem } from "./student-menu.js";

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("prefers-color-scheme"), media: query, addEventListener() {}, removeEventListener() {} })));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("a held question must be discarded when its student switches", async () => {
  const core = new FakeProfileCore();
  core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  core.health = { status: "starting", components: { core: "ok", runtime: "starting" }, readiness: "model_loading" };
  render(<App runtime={createRuntime(core.launch, core.fetch)} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
  const box = await waitFor(() => { const el = document.querySelector<HTMLElement>("[contenteditable='true']"); expect(el).not.toBeNull(); return el!; });
  fireEvent.paste(box, { clipboardData: { getData: (type: string) => type === "text/plain" ? "PRIVATE ADA QUESTION" : "" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await screen.findByText("Your question is kept and goes to the tutor as soon as it's ready.");
  fireEvent.click(menuItem("Switch student"));
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ben/ }));
  await screen.findByRole("heading", { name: /^Ready to learn, Ben\?$/ });
  core.health = { status: "ok", components: { core: "ok", runtime: "ok" }, readiness: "ready" };
  fireEvent.focus(window);
  await waitFor(() => expect(document.body.innerHTML).not.toContain("Tutor warming up"));
  expect(screen.queryByText("Your question is kept and goes to the tutor as soon as it's ready.")).toBeNull();
  expect(core.log.filter((r) => r.path.endsWith("/turns"))).toHaveLength(0);
});

test("the empty Learn screen must retain the medium-width menu button", async () => {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("min-width: 640px"), media: query, addEventListener() {}, removeEventListener() {} }));
  const core = new FakeProfileCore();
  render(<App runtime={createRuntime(core.launch, core.fetch)} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Open the menu" }));
  fireEvent.click(screen.getByRole("button", { name: "Lessons" }));
  await screen.findByText("This subject isn't on this computer yet. Add it from a USB stick, or in Settings under Content.");
  expect(screen.queryByRole("button", { name: "Open the menu" })).not.toBeNull();
});
