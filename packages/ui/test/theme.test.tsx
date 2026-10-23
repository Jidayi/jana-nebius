// DSN-05: the theme. The root element always carries the resolved `data-theme`; "Match this computer" (the default)
// follows the operating system's setting live; "Light" and "Dark" override it at once, without a reload; the dark
// value set redefines every colour the light one sets, so no light value survives a switch. The choice is kept with
// the profile's settings when the core returns the key (D91), so it applies again on the next launch; with an older
// core that does not, it lasts for the session.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { LocaleProvider } from "../src/i18n.js";
import { useAppliedPreferences } from "../src/settings/preferences.js";
import { Settings } from "../src/settings/Settings.js";
import { resolveTheme, themeOf } from "../src/settings/theme.js";

const BEN = PROFILES[1]!;
const root = document.documentElement;

/** The operating system's light or dark setting, switchable from the test. */
class SystemSetting {
  matches = false;
  readonly media = "(prefers-color-scheme: dark)";
  private readonly listeners = new Set<() => void>();
  addEventListener(_type: string, listener: () => void) { this.listeners.add(listener); }
  removeEventListener(_type: string, listener: () => void) { this.listeners.delete(listener); }
  set(dark: boolean) {
    this.matches = dark;
    for (const listener of this.listeners) listener();
  }
}

let system: SystemSetting;
beforeEach(() => {
  system = new SystemSetting();
  vi.stubGlobal("matchMedia", (query: string) => {
    expect(query).toBe(system.media);
    return system;
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  root.removeAttribute("data-theme");
});

function Shell({ profiles }: { profiles: ProfileController }) {
  useAppliedPreferences(profiles);
  return <Settings profiles={profiles} />;
}

const choice = (name: string) => screen.getByRole("radio", { name });
const patches = (core: FakeProfileCore) => core.log.filter((r) => r.method === "PATCH" && r.path.endsWith("/settings") && "theme" in (r.body as object));

describe("DSN-05", () => {
  test("dsn05_theme_switch", async () => {
    const core = new FakeProfileCore();
    const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    await profiles.load();
    render(<LocaleProvider locale="en"><Shell profiles={profiles} /></LocaleProvider>);

    // With no profile open the app follows this computer, live.
    expect(root.getAttribute("data-theme")).toBe("light");
    act(() => system.set(true));
    expect(root.getAttribute("data-theme")).toBe("dark");

    // A student's default is "Match this computer"; Light and Dark apply at once, and switching back follows the
    // computer again.
    await act(async () => { expect(await profiles.unlock(BEN.profile_id)).toBe(true); });
    await screen.findByRole("radiogroup", { name: "Theme" });
    expect(choice("Match this computer").getAttribute("aria-checked")).toBe("true");
    expect(within(screen.getByRole("radiogroup", { name: "Theme" })).getAllByRole("radio").map((r) => r.textContent)).toEqual(["Match this computer", "Light", "Dark"]);
    fireEvent.click(choice("Light"));
    expect(root.getAttribute("data-theme")).toBe("light");
    expect(choice("Light").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(choice("Dark"));
    expect(root.getAttribute("data-theme")).toBe("dark");
    act(() => system.set(false));
    expect(root.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(choice("Match this computer"));
    expect(root.getAttribute("data-theme")).toBe("light");
    // Arrow keys move the choice, as in any radio group.
    fireEvent.keyDown(choice("Match this computer"), { key: "ArrowRight" });
    expect(choice("Light").getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(choice("Light"));

    // An older core does not return the key, so nothing is sent; once it does, the choice goes to the profile's settings.
    expect(patches(core)).toEqual([]);
    core.settings.get(BEN.profile_id)!.theme = "system";
    await act(async () => { await profiles.loadSettings(); });
    expect(choice("Match this computer").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(choice("Dark"));
    await waitFor(() => expect(core.settings.get(BEN.profile_id)!.theme).toBe("dark"));
    expect(patches(core).map((r) => r.body)).toEqual([{ theme: "dark" }]);
    await waitFor(() => expect(root.getAttribute("data-theme")).toBe("dark"));

    expect(themeOf(null)).toBe("system");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");

    // No light colour survives a switch: every colour and shadow the light block sets has a dark value.
    const css = fs.readFileSync(path.join(import.meta.dirname, "../src/generated/tokens.css"), "utf8");
    const block = (selector: string) => {
      const start = css.indexOf(`${selector} {`);
      return new Set([...css.slice(start, css.indexOf("}", start)).matchAll(/--((?:color|shadow)-[a-z0-9-]+):\s*([^;]+);/g)]
        .filter((m) => !m[2]!.startsWith("var(")).map((m) => m[1]!));
    };
    const light = block(":root"), dark = block('[data-theme="dark"]');
    expect(light.size).toBeGreaterThan(60);
    expect([...light].filter((name) => !dark.has(name))).toEqual([]);
    // The stylesheet follows the attribute, never the media query alone; native controls follow it too.
    const ui = fs.readFileSync(path.join(import.meta.dirname, "../src/styles/ui.css"), "utf8");
    expect(ui).toContain('@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));');
    expect(ui).toMatch(/\[data-theme="dark"\]\s*\{\s*color-scheme: dark;/);
  });

  test("a stored theme applies again on the next launch, per profile", async () => {
    // The core kept Ben's "Dark" from an earlier run; this computer is light. A fresh app (no session choice) opens
    // Ben dark at once, and a profile without a stored choice follows the computer.
    const core = new FakeProfileCore();
    core.settings.get(BEN.profile_id)!.theme = "dark";
    const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    await profiles.load();
    render(<LocaleProvider locale="en"><Shell profiles={profiles} /></LocaleProvider>);
    expect(root.getAttribute("data-theme")).toBe("light");
    await act(async () => { expect(await profiles.unlock(BEN.profile_id)).toBe(true); });
    await waitFor(() => expect(root.getAttribute("data-theme")).toBe("dark"));
    expect((await screen.findByRole("radio", { name: "Dark" })).getAttribute("aria-checked")).toBe("true");
    expect(patches(core)).toEqual([]);
  });
});
