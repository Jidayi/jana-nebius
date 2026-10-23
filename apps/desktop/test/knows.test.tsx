// UXS-28 and LRN-36 in the app as it is wired: "What the tutor knows" opens from Settings for the unlocked profile,
// lists that profile's notes, forgets one, and goes back; switching student leaves none of its notes behind (SEC-19).
// Against the fake core (client-core's test fake); every note is synthetic.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { FakeProfileCore, PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { findMenuItem } from "./student-menu.js";

const [ADA] = PROFILES as [(typeof PROFILES)[number]];
const NOTE = { note_id: `mem_${"1".repeat(26)}`, text: "ADA-NOTE Checks the units before the final answer", created_ts: Date.UTC(2026, 9, 8, 12), source: "reflector" as const };

afterEach(() => cleanup());

describe("UXS-28", () => {
  test("the knows page opens from Settings and forgets a note", async () => {
    const core = new FakeProfileCore();
    core.notes.set(ADA.profile_id, [{ ...NOTE }]);
    const runtime = createRuntime(core.launch, core.fetch);
    render(<App runtime={runtime} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
    fireEvent.click(await findMenuItem("Settings"));
    fireEvent.click(await screen.findByRole("button", { name: "What the tutor knows about you" }));
    await screen.findByRole("heading", { name: "What the tutor knows about you" });
    const row = await waitFor(() => {
      const found = document.querySelector(`[data-note-id="${NOTE.note_id}"]`);
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    fireEvent.click(within(row).getByRole("button", { name: "Remove this note" }));
    await screen.findByText("Removed. Your tutor won't use that note again.");
    expect(core.notes.get(ADA.profile_id)).toEqual([]);
    // Back returns to Settings, where the page was opened from.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await screen.findByRole("heading", { name: "Settings" });

    // A switch of student empties the page's data with everything else.
    core.notes.set(ADA.profile_id, [{ ...NOTE }]);
    await runtime.knows.load();
    expect(JSON.stringify(runtime.knows.getView())).toContain("ADA-NOTE");
    await runtime.profiles.lock();
    expect(JSON.stringify(runtime.knows.getView())).not.toContain("ADA-NOTE");
  });
});
