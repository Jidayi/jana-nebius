// DSN-26, DSN-27, UXS-54 and PRM-03 in the UI: the six tutor characters on one rig (their ids, colours and art
// rules), the static poses reduced motion shows, the one pick of Settings → Tutor and the first-session interview, and
// one tutor per profile whose name labels its turns (D105). Synthetic settings only; no real student data.
import fs from "node:fs";
import path from "node:path";
import { useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import type { ProfileController } from "@jana/client-core";
import type { Settings, SettingsPatch } from "@jana/contracts-ts";
import { BASE } from "@jana/i18n";
import { TOKENS } from "../src/generated/tokens.js";
import { LocaleProvider } from "../src/i18n.js";
import { TUTOR_AVATARS, TutorLookProvider, TutorSection, tutorAvatarOf } from "../src/settings/TutorSection.js";
import { CHARACTER_IDS, CHARACTER_MOUTHS, CHARACTER_POSES, CHARACTER_SVG_BUDGET_BYTES, DEFAULT_CHARACTER, slugOf } from "../src/tutor/characters.js";
import { Character, TutorPresence } from "../src/tutor/Character.js";
import { FirstRunTutorPick } from "../src/tutor/TutorPick.js";
import { GalleryView, STATES } from "../gallery/index.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");
const read = (p: string) => fs.readFileSync(path.join(ROOT, p), "utf8");

afterEach(() => cleanup());

const BASE_SETTINGS: Settings = {
  low_power: false, text_scale: 1, locale: "en", memory_saving: true, notifications: false, reduced_motion: false, read_aloud: false,
  easy_read: false, extra_time_percent: 0, tutor_name: "Jana", tutor_avatar: "avatar.jana",
};

/** A profile controller stand-in that keeps every settings patch and answers as the core does (or refuses). */
function profilesFor(calls: SettingsPatch[], answer: (patch: SettingsPatch) => Promise<Settings>) {
  return { setPreferences: (patch: SettingsPatch) => { calls.push(patch); return answer(patch); } } as unknown as ProfileController;
}

/** Settings → Tutor over settings that follow what was saved, as the app re-renders from the core's answer. */
function SettingsHarness({ calls, refuse = false }: { calls: SettingsPatch[]; refuse?: boolean }) {
  const [settings, setSettings] = useState<Settings>(BASE_SETTINGS);
  const profiles = profilesFor(calls, async (patch) => {
    if (refuse) throw Object.assign(new Error("refused"), { code: "validation_failed" });
    const next = { ...settings, ...patch } as Settings;
    setSettings(next);
    return next;
  });
  return <LocaleProvider locale="en"><TutorSection profiles={profiles} settings={settings} /></LocaleProvider>;
}

// --- colour helpers (WCAG relative luminance) -------------------------------------------------------------------------
const rgb = (hex: string) => [0, 2, 4].map((i) => parseInt(hex.replace("#", "").slice(i, i + 2), 16));
function luminance(hex: string): number {
  const [r, g, b] = rgb(hex).map((c) => c / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}
/** The middle of a body's two-stop gradient. */
function mid(a: string, b: string): string {
  const [x, y] = [rgb(a), rgb(b)];
  return `#${x.map((c, i) => Math.round((c + y[i]!) / 2).toString(16).padStart(2, "0")).join("")}`;
}

type Token = { light: string; dark: string };
const COLOURS = TOKENS.color as unknown as Record<string, Token>;

describe("DSN-26", () => {
  test("dsn26_character_set_matches_contract", () => {
    const commands = JSON.parse(read("services/agent-core/agent_core/contracts/schemas/api/commands.schema.json")) as { $defs: Record<string, { properties: Record<string, { enum?: string[] }> }> };
    for (const def of ["Settings", "SettingsPatch"]) expect([...CHARACTER_IDS], def).toEqual(commands.$defs[def]!.properties.tutor_avatar!.enum);
    expect(CHARACTER_IDS).toEqual(["avatar.jana", "avatar.orbit", "avatar.prism", "avatar.kite", "avatar.pebble", "avatar.ray"]);
    expect(DEFAULT_CHARACTER).toBe("avatar.jana");
    expect([...TUTOR_AVATARS]).toEqual([...CHARACTER_IDS]);
    // The identity file's default tutor is the Jana character.
    expect(read("content/agent/soul/IDENTITY.yaml")).toMatch(/^avatar_id:\s*avatar\.jana\s*$/m);
    // A stored value outside the set reads as Jana (G119, D103): the old picture ids, unknown ids, nothing stored.
    for (const old of ["avatar.default", "avatar.disc_3", "avatar.unknown", 7, undefined]) {
      expect(tutorAvatarOf({ ...BASE_SETTINGS, tutor_avatar: old as never }), String(old)).toBe("avatar.jana");
    }
    expect(tutorAvatarOf(null)).toBe("avatar.jana");
    for (const id of CHARACTER_IDS) expect(tutorAvatarOf({ ...BASE_SETTINGS, tutor_avatar: id })).toBe(id);
    // Every character draws on the one rig, and each has its name and hint in the catalogue.
    for (const id of CHARACTER_IDS) {
      const { container } = render(<Character id={id} />);
      expect(container.querySelector(`svg[data-character="${id}"]`), id).not.toBeNull();
      expect(BASE[`tutor.character.${slugOf(id)}.name`], id).toBeTruthy();
      expect(BASE[`tutor.character.${slugOf(id)}.hint`], id).toBeTruthy();
      cleanup();
    }
  });

  test("dsn26_character_contrast", () => {
    const reserved = ["verified", "misconception"].flatMap((r) => [r, `${r}-soft`, `${r}-line`]).flatMap((r) => [COLOURS[r]!.light, COLOURS[r]!.dark]).map((c) => c.toUpperCase());
    for (const id of CHARACTER_IDS) {
      const slug = slugOf(id);
      const token = (part: string) => COLOURS[`character-${slug}-${part}`]!;
      for (const theme of ["light", "dark"] as const) {
        const [start, end, feature] = [token("start")[theme], token("end")[theme], token("feature")[theme]];
        expect(ratio(feature, mid(start, end)), `${slug} features on the mid-body (${theme})`).toBeGreaterThanOrEqual(3);
        if (theme === "light") {
          // The deep stop carries the body on paper, except Remy's yellow, whose name and state word carry it (VOC-17).
          const deep = luminance(start) < luminance(end) ? start : end;
          if (slug !== "ray") expect(ratio(deep, COLOURS.paper!.light), `${slug} deep stop on paper`).toBeGreaterThanOrEqual(3);
        } else {
          for (const stop of [start, end]) for (const surface of ["paper", "canvas"]) {
            expect(ratio(stop, COLOURS[surface]!.dark), `${slug} ${stop} on dark ${surface}`).toBeGreaterThanOrEqual(3);
          }
        }
        for (const part of ["start", "end", "accent-start", "accent-end", "feature"]) {
          expect(reserved, `${slug}-${part} (${theme}) is a learning colour`).not.toContain(token(part)[theme].toUpperCase());
        }
      }
    }
  });

  test("dsn26_character_art_rules", () => {
    const files = ["packages/ui/src/tutor/art.tsx", "packages/ui/src/tutor/Character.tsx", "packages/ui/src/tutor/presence.css"];
    const allowed = /^(character-(jana|orbit|prism|kite|pebble|ray)-(start|end|accent-start|accent-end|feature)|student|tutor|ink)$/;
    for (const file of files) {
      const code = read(file).replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
      // No raster image, photo or embedded picture; no filter or backdrop-filter (DSN-26).
      expect(code, file).not.toMatch(/<image\b|<img\b|<foreignObject|data:image|\.(png|jpe?g|webp|gif|avif)\b/i);
      expect(code, file).not.toMatch(/backdrop-filter|<filter\b|(^|[^.\w-])filter\s*[=:]/m);
      // Colours only from the character tokens (plus the indicators' student and tutor roles and the silhouette's
      // ink) and white for the sheen: no raw colour, no skin tone.
      expect(code, file).not.toMatch(/#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(/i);
      expect(code, file).not.toMatch(/\b(skin|flesh|peach|beige|tan|brown|black|red|green|pink)\b/i);
      for (const m of code.matchAll(/var\(--color-([a-z0-9-]+)\)/g)) expect(m[1], file).toMatch(allowed);
      // No asset for a frown, sadness or disappointment.
      expect(code, file).not.toMatch(/frown|\bsad|disappoint|\bcry|tear/i);
    }
    const art = read("packages/ui/src/tutor/art.tsx") + read("packages/ui/src/tutor/Character.tsx");
    for (const m of art.matchAll(/(?:fill|stroke|stopColor|stop-color)=["']([a-zA-Z]+)["']/g)) expect(["none", "white"], m[0]).toContain(m[1]);
    let curves = 0;
    for (const id of CHARACTER_IDS) {
      for (const pose of CHARACTER_POSES) {
        for (const mouth of pose === "speaking" ? CHARACTER_MOUTHS : [undefined]) {
          const markup = renderToStaticMarkup(<Character id={id} pose={pose} {...(mouth !== undefined ? { mouth } : {})} />);
          // Within the art budget, decorative (the words beside it name the tutor), and every line mouth turns up or
          // is level: a curved mouth line never bends down.
          expect(new TextEncoder().encode(markup).length, `${id} ${pose}`).toBeLessThanOrEqual(CHARACTER_SVG_BUDGET_BYTES);
          expect(markup, `${id} ${pose}`).toMatch(/^<svg[^>]*aria-hidden="true"/);
          expect(markup).not.toMatch(/<title|role="img"/);
          expect(/data-part="mouth"/.test(markup), `${id} ${pose} has a mouth`).toBe(pose !== "silhouette");
          for (const d of markup.matchAll(/data-part="mouth" data-line=""[^>]*\bd="M\s*(-?[\d.]+)[ ,](-?[\d.]+)\s*Q\s*(-?[\d.]+)[ ,](-?[\d.]+)\s+(-?[\d.]+)[ ,](-?[\d.]+)/g)) {
            curves += 1;
            const [y1, cy, y2] = [Number(d[2]), Number(d[4]), Number(d[6])];
            expect(cy, `${id} ${pose} mouth ${d[0]}`).toBeGreaterThanOrEqual(Math.max(y1, y2));
          }
        }
      }
    }
    expect(curves).toBeGreaterThan(CHARACTER_IDS.length);
    // Gradient ids are unique per drawing, so two characters on one screen never share a fill.
    const { container } = render(<><Character id="avatar.orbit" /><Character id="avatar.orbit" /></>);
    const ids = [...container.querySelectorAll("[id]")].map((el) => el.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("DSN-27", () => {
  const css = read("packages/ui/src/tutor/presence.css");
  const animated = [...css.matchAll(/\.(presence-[a-z0-9-]+)\s*\{[^}]*animation:/g)].map((m) => m[1]!);

  test("dsn27_reduced_motion_static_pose", () => {
    expect(animated.length).toBeGreaterThan(5);
    // The presence primitive animates only transform and opacity, and both the system setting and the app's own
    // Reduce motion (or low-power) attribute stop every animation and show the rest mouth.
    for (const block of css.matchAll(/@keyframes\s+[a-z0-9-]+\s*\{([\s\S]*?)\n\}/g)) {
      for (const prop of block[1]!.matchAll(/([a-z-]+)\s*:/g)) expect(["transform", "opacity"], block[0].slice(0, 40)).toContain(prop[1]);
    }
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*\.presence-motion[^{]*\{[^}]*animation:\s*none/);
    expect(css).toMatch(/\[data-reduced-motion="true"\] \.presence-motion[^{]*\{[^}]*animation:\s*none/);
    expect(css).toMatch(/\[data-reduced-motion="true"\] \.presence-shape[^{]*\{[^}]*opacity:\s*0/);
    expect(css).toMatch(/\[data-reduced-motion="true"\] \.presence-rest[^{]*\{[^}]*opacity:\s*1/);
    for (const id of CHARACTER_IDS) {
      for (const pose of CHARACTER_POSES) {
        // Animating: every animated element is one the reduced-motion rules reach.
        const { container, unmount } = render(<div data-reduced-motion="true"><Character id={id} pose={pose} mouth="open" /></div>);
        for (const el of container.querySelectorAll("[class]")) {
          const classes = [...el.classList];
          if (classes.some((c) => animated.includes(c))) expect(classes, `${id} ${pose}`).toContain("presence-motion");
        }
        if (pose === "speaking") expect(container.querySelector('[data-part="mouth"][data-mouth="closed"].presence-rest'), id).not.toBeNull();
        unmount();
        // Low power and stills: no animated element at all, the rest mouth only, the pose's indicator kept.
        const still = render(<Character id={id} pose={pose} mouth="open" animate={false} />);
        expect(still.container.querySelectorAll(".presence-motion"), `${id} ${pose}`).toHaveLength(0);
        expect(still.container.querySelector("svg")?.getAttribute("data-animate")).toBe("false");
        if (pose === "speaking") expect([...still.container.querySelectorAll('[data-part="mouth"]')].map((m) => m.getAttribute("data-mouth"))).toEqual(["closed"]);
        if (["listening", "thinking", "speaking"].includes(pose)) expect(still.container.querySelector("[data-indicator]"), `${id} ${pose}`).not.toBeNull();
        still.unmount();
      }
    }
    // The presence shows each voice state's words beside the drawing, which announces nothing itself (VOC-17).
    for (const state of ["idle", "listening", "thinking", "speaking", "interrupted", "unavailable"] as const) {
      const { container } = render(<LocaleProvider locale="en"><TutorPresence id="avatar.pebble" state={state} /></LocaleProvider>);
      expect(container.textContent, state).toContain(BASE[`voice.state.${state}`]);
      expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
      if (state === "unavailable") expect(container.querySelector("svg")?.getAttribute("data-animate")).toBe("false");
      cleanup();
    }
  });
});

describe("UXS-54", () => {
  const nameField = () => screen.getByRole("textbox", { name: BASE["settings.tutor.rename"] }) as HTMLInputElement;
  const radio = (name: string) => screen.getByRole("radio", { name });

  test("uxs54_one_pick_sets_character_and_name", async () => {
    const calls: SettingsPatch[] = [];
    render(<SettingsHarness calls={calls} />);
    expect((radio("Jana") as HTMLInputElement).checked).toBe(true);
    expect(nameField().value).toBe("Jana");
    // Choosing a tile fills the name with the character's default name; Save writes both in one patch.
    fireEvent.click(radio("Orbit"));
    expect(nameField().value).toBe("Orbit");
    fireEvent.click(screen.getByRole("button", { name: BASE["settings.tutor.save"] }));
    await waitFor(() => expect(calls).toEqual([{ tutor_avatar: "avatar.orbit", tutor_name: "Orbit" }]));
    await screen.findByText("Your tutor is called Orbit.");
    // A name the student typed first is kept when they choose another character.
    fireEvent.change(nameField(), { target: { value: "Ama" } });
    fireEvent.click(radio("Prism"));
    expect(nameField().value).toBe("Ama");
    fireEvent.click(screen.getByRole("button", { name: BASE["settings.tutor.save"] }));
    await waitFor(() => expect(calls.at(-1)).toEqual({ tutor_avatar: "avatar.prism", tutor_name: "Ama" }));
    // Reset to Jana restores the Jana character and the name Jana, in one patch.
    fireEvent.click(await screen.findByRole("button", { name: "Reset to Jana" }));
    await waitFor(() => expect(calls.at(-1)).toEqual({ tutor_avatar: "avatar.jana", tutor_name: "Jana" }));
    await screen.findByText("Your tutor is called Jana.");
    expect(calls).toHaveLength(3);
    cleanup();

    // A name the core refuses (PRV-03) shows the field's error and keeps the student's words.
    const refused: SettingsPatch[] = [];
    render(<SettingsHarness calls={refused} refuse />);
    fireEvent.change(nameField(), { target: { value: "@@@" } });
    fireEvent.click(screen.getByRole("button", { name: BASE["settings.tutor.save"] }));
    await screen.findByText(BASE["settings.tutor.name_refused"]!);
    expect(nameField().getAttribute("aria-invalid")).toBe("true");
    expect(nameField().value).toBe("@@@");
    cleanup();

    // The first-session interview opens with the same pick: "Keep Jana" saves nothing, a choice saves one patch.
    let done = 0;
    const first: SettingsPatch[] = [];
    const firstProfiles = profilesFor(first, async (patch) => ({ ...BASE_SETTINGS, ...patch } as Settings));
    render(<LocaleProvider locale="en"><FirstRunTutorPick profiles={firstProfiles} settings={BASE_SETTINGS} onDone={() => { done += 1; }} /></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Keep Jana" }));
    expect(done).toBe(1);
    expect(first).toEqual([]);
    cleanup();
    render(<LocaleProvider locale="en"><FirstRunTutorPick profiles={firstProfiles} settings={BASE_SETTINGS} onDone={() => { done += 1; }} /></LocaleProvider>);
    fireEvent.click(radio("Kite"));
    fireEvent.click(screen.getByRole("button", { name: BASE["tutor.pick.choose"] }));
    await waitFor(() => expect(done).toBe(2));
    expect(first).toEqual([{ tutor_avatar: "avatar.kite", tutor_name: "Kite" }]);
  });

  test("uxs54_tutor_pick_gallery", () => {
    const pick = STATES.filter((s) => s.component === "SettingsTutor" || s.component === "FirstRunTutorPick");
    const has = (component: string, state: string, variant?: string) => pick.some((s) => s.component === component && s.state === state && s.variant === variant);
    // Canonical (Jana selected), another character, a custom name, a refused name; the interview's pick.
    expect(has("SettingsTutor", "canonical")).toBe(true);
    expect(has("SettingsTutor", "canonical", "other-character")).toBe(true);
    expect(has("SettingsTutor", "canonical", "custom-name")).toBe(true);
    expect(has("SettingsTutor", "error-retriable", "name-refused")).toBe(true);
    expect(has("FirstRunTutorPick", "canonical")).toBe(true);
    for (const state of pick) {
      for (const theme of ["light", "dark"]) {
        const { container } = render(<GalleryView state={{ ...state, context: { ...state.context, theme } }} />);
        const radios = [...container.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
        expect(radios, state.id).toHaveLength(6);
        const chosen = radios.filter((r) => r.checked);
        expect(chosen, state.id).toHaveLength(1);
        // Identifiable in greyscale: the chosen tile alone has the tick and the border on the neutral wash, and no
        // blue marks it.
        const tiles = [...container.querySelectorAll<HTMLElement>("[data-character-tile]")];
        expect(tiles, state.id).toHaveLength(6);
        for (const tile of tiles) {
          const selected = tile.contains(chosen[0]!);
          expect(tile.querySelector("[data-selected-mark] svg") !== null, `${state.id} ${tile.dataset.characterTile}`).toBe(selected);
          expect(tile.className.includes("bg-wash") && tile.className.includes("border-ink"), `${state.id} ${tile.dataset.characterTile}`).toBe(selected);
          expect(tile.className, state.id).not.toMatch(/accent|blue|action/);
        }
        if (state.variant === "name-refused") expect(container.textContent).toContain(BASE["settings.tutor.name_refused"]);
        cleanup();
      }
    }
  });
});

describe("PRM-03", () => {
  test("prm03_one_tutor_per_profile", async () => {
    // One pick for the one tutor: a single group of six characters and a single name.
    const calls: SettingsPatch[] = [];
    render(<SettingsHarness calls={calls} />);
    expect(screen.getAllByRole("radiogroup")).toHaveLength(1);
    expect(screen.getAllByRole("radio")).toHaveLength(6);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    fireEvent.click(screen.getByRole("radio", { name: "Remy" }));
    fireEvent.click(screen.getByRole("button", { name: BASE["settings.tutor.save"] }));
    await waitFor(() => expect(calls).toHaveLength(1));
    // Re-skinning and renaming only touch the tutor's look and name: no other setting, memory or learner key.
    for (const patch of calls) for (const key of Object.keys(patch)) expect(["tutor_avatar", "tutor_name"]).toContain(key);
    cleanup();
    // The tutor's turns carry its name (D105), Jana by default, and its chosen character, drawn once and still.
    const turn = STATES.find((s) => s.id === "tutor-turn.canonical")!;
    const plain = render(<GalleryView state={turn} />);
    expect(plain.getByRole("region", { name: "Jana" })).toBeTruthy();
    expect(plain.container.querySelector('[data-turn-id] svg[data-character="avatar.jana"]')).not.toBeNull();
    plain.unmount();
    const { container, getByRole } = render(<TutorLookProvider avatar="avatar.ray" name="Ama"><GalleryView state={turn} /></TutorLookProvider>);
    const region = getByRole("region", { name: "Ama" });
    expect(within(region).getByText("Ama")).toBeTruthy();
    const marks = container.querySelectorAll("[data-turn-id] svg[data-character]");
    expect(marks).toHaveLength(1);
    expect(marks[0]!.getAttribute("data-character")).toBe("avatar.ray");
    expect(marks[0]!.getAttribute("data-animate")).toBe("false");
    expect(container.textContent).not.toMatch(/\bTutor\b/);
  });
});
