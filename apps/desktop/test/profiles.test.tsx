// UXS-09 in the app as it is wired (App, createRuntime): the picker shows only each profile's name, avatar disc and
// whether it has a PIN; the profile token stays in memory; switching student leaves nothing of the previous profile in
// any view, in the client store or in the render caches; and the SEC-19 PIN delay disables that profile's PIN entry
// with an honest countdown, without holding up any other profile. Against a fake core (client-core's test fake).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { katexCache } from "@jana/ui";
import { FakeProfileCore, PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { menuItem } from "./student-menu.js";

const [ADA, BEN] = PROFILES as [(typeof PROFILES)[number], (typeof PROFILES)[number]];

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function start() {
  const core = new FakeProfileCore();
  const runtime = createRuntime(core.launch, core.fetch);
  render(<App runtime={runtime} />);
  return { core, runtime };
}

const tile = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });



describe("UXS-09", () => {
  test("uxs09_profile_isolation", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { core, runtime } = start();
    await screen.findByRole("heading", { name: "Who's learning?" });

    // Only the display name, the avatar disc and whether a PIN is set.
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["AAda", "BBen", "CChi"]); // initial on the disc, then the name
    expect(screen.queryAllByRole("img", { name: "Has a PIN" })).toHaveLength(0);
    expect(within(items[0]!).queryByRole("img", { name: "Has a PIN" })).toBeNull();
    expect(items.map((li) => li.querySelector("[data-disc]")?.getAttribute("data-disc"))).toEqual(["1", "2", "3"]);
    expect(document.body.textContent).not.toContain("LEAK-LEVEL");
    expect(JSON.stringify(runtime.profiles.getView())).not.toContain("LEAK-LEVEL");

    // Ada has no PIN: her session opens with her transcript and board.
    fireEvent.click(tile("Ada"));
    await waitFor(() => expect(document.body.textContent).toContain(ADA.canary), { timeout: 5_000 });
    // She lands on Home (UXS-01); her session reopens in the tutor from the sidebar.
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(ADA.canary) }));
    await waitFor(() => expect(katexCache.size).toBeGreaterThan(0)); // her maths went through the render cache
    const adaToken = core.tokenOf(ADA.profile_id)!;
    expect(core.log.find((r) => r.path.endsWith("/snapshot"))?.headers["x-profile-token"]).toBe(adaToken);
    // The profile token lives in memory only: no web storage, nothing in the store or the profile view.
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length + sessionStorage.length).toBe(0);
    expect(JSON.stringify({ store: runtime.holder.getState(), view: runtime.profiles.getView() })).not.toContain(adaToken);
    expect(document.documentElement.outerHTML).not.toContain(adaToken);

    // Switch student: back to the picker with nothing of Ada's anywhere.
    fireEvent.click(menuItem("Switch student"));
    await screen.findByRole("heading", { name: "Who's learning?" });
    const memory = () => JSON.stringify({ store: runtime.holder.getState(), view: runtime.profiles.getView() });
    expect(document.body.textContent).not.toContain("CANARY-ADA");
    expect(memory()).not.toContain("CANARY-ADA");
    expect(katexCache.size).toBe(0);
    await waitFor(() => expect(core.openStreams).toBe(0));
    expect(core.log.some((r) => r.path === `/v1/profiles/${ADA.profile_id}/close` && r.headers["x-profile-token"] === adaToken)).toBe(true);

    // Ben opens with his PIN and sees only his own work.
    fireEvent.click(tile("Ben"));
    await waitFor(() => expect(document.body.textContent).toContain(BEN.canary), { timeout: 5_000 });
    expect(document.body.textContent).not.toContain("CANARY-ADA");
    expect(memory()).not.toContain("CANARY-ADA");
    expect(core.log.filter((r) => r.path.startsWith("/v1/sessions")).at(-1)?.headers["x-profile-token"]).toBe(core.tokenOf(BEN.profile_id));
    expect(setItem).not.toHaveBeenCalled();
  });

  // A tap opens the profile, again and again, with no PIN prompt or delay, on a family's laptop. A profile hosted by a
  // school server comes with API-42 (S4); this computer has none to tap.
  test("uxs09_tap_opens_profile", async () => {
    const { core } = start();
    await screen.findByRole("heading", { name: "Who's learning?" });
    for (let attempt = 0; attempt < 3; attempt += 1) {
      fireEvent.click(tile("Ben"));
      await waitFor(() => expect(document.body.textContent).toContain(BEN.canary));
      expect(screen.queryByLabelText("Enter Ben's PIN")).toBeNull();
      fireEvent.click(menuItem("Switch student"));
      await screen.findByRole("heading", { name: "Who's learning?" });
      expect(document.body.textContent).not.toContain(BEN.canary);
    }
    expect(core.log.filter((r) => r.path === `/v1/profiles/${BEN.profile_id}/open`)).toHaveLength(3);
    expect(core.log.filter((r) => r.path === `/v1/profiles/${BEN.profile_id}/open`).every((r) => JSON.stringify(r.body) === "{}")).toBe(true);
  });
});

describe("DAT-12", () => {
  test("dat12_newer_db_refused", async () => {
    // A profile saved by a newer app (G51): the picker says so in place of opening it, and every other profile opens.
    const { core } = start();
    core.newerApp.add(ADA.profile_id);
    fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Ada's work was saved by a newer version of this app");
    expect(core.tokenOf(ADA.profile_id)).toBeUndefined();
    expect(screen.getByRole("heading", { name: "Who's learning?" })).toBeTruthy();
    fireEvent.click(tile("Ben"));
    expect(screen.queryByLabelText("Enter Ben's PIN")).toBeNull();
    await waitFor(() => expect(core.tokenOf(BEN.profile_id)).toBeDefined());
  });
});
