// UXS-53 and DSN-27 (D103): the tutor's presence in voice mode follows the voice state at once with the VOC-04 words
// beside it, sits by the layout (docked on the open board and pointing there, by the composer with the board closed,
// above it at phone width), has a gallery state for each state, and runs no motion with reduced motion, in low-power
// mode or on the calm screen.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { SpeechController, VoiceView } from "@jana/client-core";
import { BASE } from "@jana/i18n";
import { TutorScreen } from "../src/TutorScreen.js";
import { StudioFrame } from "../src/frame/Frame.js";
import { VoicePresence, presencePlacement } from "../src/tutor/VoicePresence.js";
import { VisualSettingsProvider } from "../src/visuals/VisualViewer.js";
import { SpeechToolsProvider } from "../src/voice/SpeechTools.js";
import { VoiceBarView } from "../src/voice/VoiceBar.js";
import { GalleryView, type GalleryState } from "../gallery/index.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const BOARD = `brd_${"5".repeat(26)}`;
const LINE = `stp_${"1".repeat(26)}`;
const VIEW: VoiceView = { connected: true, state: "idle", mode: "hands_free", reason: null, student: "", tentative: "", tutor: "", words: [],
  playedMs: 0, captionItem: null, pointer: null, writing: null };
/** The VOC-04 state fixture: a hands-free exchange with a barge-in, then the voice becoming unavailable. */
const VOC04 = ["idle", "listening", "thinking", "speaking", "interrupted", "listening", "thinking", "speaking", "idle", "unavailable"] as const;

/** The session's voice as the presence reads it. */
function voice(start: Partial<VoiceView> = {}) {
  const listeners = new Set<() => void>();
  let view: VoiceView = { ...VIEW, ...start };
  const speech = { available: false, partId: null, reading: false, text: "", charIndex: 0, dictation: "idle", draft: null, error: null };
  const controller = { subscribe: () => () => undefined, getState: () => speech,
    voice: { subscribe: (l: () => void) => { listeners.add(l); return () => listeners.delete(l); }, getState: () => view } };
  return {
    controller: controller as unknown as SpeechController,
    set(change: Partial<VoiceView>) { act(() => { view = { ...view, ...change }; for (const l of listeners) l(); }); },
  };
}

const presence = () => document.querySelector<HTMLElement>("[data-presence-placement]");

describe("UXS-53", () => {
  test("uxs53_presence_follows_voice_state", () => {
    const v = voice();
    new Fixture().render(<SpeechToolsProvider controller={v.controller}><VoicePresence placement="floating" /></SpeechToolsProvider>);
    for (const state of VOC04) {
      const sent = performance.now();
      v.set({ state });
      // The presence is in the state's pose with its VOC-04 words beside it, within 100 ms of the state changing.
      expect(presence()?.querySelector("[data-presence]")?.getAttribute("data-presence")).toBe(state);
      expect(performance.now() - sent).toBeLessThan(100);
      expect(presence()?.textContent).toContain(BASE[`voice.state.${state}`]);
      expect(presence()?.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    }
    // Voice off (not connected): no living presence.
    v.set({ connected: false });
    expect(presence()).toBeNull();
  });

  test("uxs53_presence_placement", () => {
    expect([presencePlacement("wide", true), presencePlacement("expanded", false), presencePlacement("compact", true)])
      .toEqual(["docked", "floating", "phone"]);
    const v = voice({ state: "speaking" });
    const f = new Fixture();
    f.startTurn();
    f.emit({ type: "board.step", board_id: BOARD, step_id: LINE, index: 0, latex: "2x = 10", reason: null, owner: "tutor", status: "final", check_id: null, error: null }, null);
    f.render(<SpeechToolsProvider controller={v.controller}><TutorScreen sessionId={SESSION} /></SpeechToolsProvider>);
    // The board is open beside the conversation: the presence is docked at the top of its panel, before the lines...
    const panel = document.querySelector("[data-board-panel]") as HTMLElement;
    expect(panel.firstElementChild?.getAttribute("data-presence-placement")).toBe("docked");
    // ...and points while the tutor's pointer is on a step.
    v.set({ pointer: { target: { kind: "step", step_id: LINE }, fired_ms: 0, word_ms: 0, timing: "estimated" } });
    expect(presence()?.getAttribute("data-presence-pointing")).toBe("true");
    expect(presence()?.querySelector("svg")?.getAttribute("data-pose")).toBe("pointing");
    // The board closed: it floats by the composer, outside the board.
    fireEvent.click(screen.getByRole("button", { name: BASE["board.hide"] }));
    expect(presence()?.getAttribute("data-presence-placement")).toBe("floating");
    expect(presence()?.closest("[data-region='board']")).toBeNull();
    expect(presence()?.querySelector("svg")?.getAttribute("data-pose")).not.toBe("pointing");
    cleanup();
    // At phone width it sits above the composer.
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
    const g = new Fixture();
    g.render(<SpeechToolsProvider controller={v.controller}><StudioFrame sidebar={() => null}><TutorScreen sessionId={SESSION} /></StudioFrame></SpeechToolsProvider>);
    expect(document.querySelector("[data-layout]")?.getAttribute("data-layout")).toBe("compact");
    expect(presence()?.getAttribute("data-presence-placement")).toBe("phone");
    const composer = document.querySelector("textarea, [role='textbox']") as HTMLElement;
    expect(composer).not.toBeNull();
    expect((presence()?.compareDocumentPosition(composer) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
  });

  test("uxs53_presence_states_gallery", () => {
    const folder = join(dirname(fileURLToPath(import.meta.url)), "..", "gallery", "states");
    const states = readdirSync(folder).filter((n) => n.startsWith("tutor-presence."))
      .map((n) => JSON.parse(readFileSync(join(folder, n), "utf8")) as GalleryState);
    // Each declared state (every voice state, and pointing) has a gallery state, canonical and in reduced motion...
    for (const variant of ["idle", "listening", "thinking", "speaking", "interrupted", "unavailable", "pointing"]) {
      for (const kind of ["canonical", "reduced-motion"]) {
        const found = states.find((s) => s.state === kind && s.variant === variant);
        expect(found, `${kind} ${variant}`).toBeDefined();
        // ...rendered in both themes; in reduced motion it is marked so the static pose shows with nothing running.
        for (const theme of ["light", "dark"]) {
          const { container } = render(<GalleryView state={{ ...(found as GalleryState), context: { ...(found as GalleryState).context, theme } }} />);
          expect(container.querySelector(`[data-theme="${theme}"] [data-presence]`), `${kind} ${variant} ${theme}`).not.toBeNull();
          if (kind === "reduced-motion") expect(container.querySelector("[data-reduced-motion='true']"), `${variant} ${theme}`).not.toBeNull();
          cleanup();
        }
      }
    }
    // A screen reader hears each state change once, in words: the voice bar's polite live region, never the drawing.
    const actions = { onToggle: vi.fn(), onConversation: vi.fn(), onRestart: vi.fn(), onMode: vi.fn(), onHold: vi.fn(), onStop: vi.fn() };
    const v = voice();
    const f = new Fixture();
    const view = f.render(<SpeechToolsProvider controller={v.controller}><VoiceBarView view={VIEW} starting={false} restart={false} actions={actions} /><VoicePresence placement="floating" /></SpeechToolsProvider>);
    for (const state of VOC04) {
      v.set({ state });
      view.rerender(<SpeechToolsProvider controller={v.controller}><VoiceBarView view={{ ...VIEW, state }} starting={false} restart={false} actions={actions} /><VoicePresence placement="floating" /></SpeechToolsProvider>);
      const live = [...document.querySelectorAll("[aria-live='polite']")].filter((el) => el.textContent?.includes(BASE[`voice.state.${state}`] ?? "?"));
      expect(live, state).toHaveLength(1);
      expect(presence()?.querySelector("[aria-live], [role='status']")).toBeNull();
    }
  });
});

describe("DSN-27", () => {
  test("dsn27_reduced_motion_static_pose", () => {
    const v = voice({ state: "speaking", mouth: "open" });
    const f = new Fixture();
    f.render(<div data-reduced-motion="true"><VisualSettingsProvider settings={{ reducedMotion: true, textScale: 1 }}>
      <SpeechToolsProvider controller={v.controller}><VoicePresence placement="floating" /></SpeechToolsProvider></VisualSettingsProvider></div>);
    // Reduced motion: every state renders its static pose and indicator; the animation classes are the presence
    // primitive's only (presence-motion), which the reduced-motion rules stop, and the speaking mouth has its rest shape.
    for (const state of ["idle", "listening", "thinking", "speaking", "interrupted"] as const) {
      v.set({ state });
      const drawing = presence()?.querySelector("svg") as SVGElement;
      for (const el of drawing.querySelectorAll("[class*='presence-']")) {
        const classes = el.getAttribute("class") ?? "";
        if (/presence-(breathe|blink|bob|lean|glance|dot|wave|beat|tilt|point|oh)\b/.test(classes)) expect(classes, state).toContain("presence-motion");
      }
      if (state === "speaking") expect(drawing.querySelector('[data-mouth="closed"].presence-rest')).not.toBeNull();
      if (state !== "idle" && state !== "interrupted") expect(drawing.querySelector("[data-indicator]"), state).not.toBeNull();
    }
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "tutor", "presence.css"), "utf8");
    expect(css).toMatch(/\[data-reduced-motion="true"\] \.presence-motion \{\s*animation: none;/);
  });

  test("dsn27_no_motion_low_power_or_calm", () => {
    const v = voice({ state: "speaking", mouth: "open" });
    // Low power: the static pose, nothing animated at all.
    new Fixture().render(<VisualSettingsProvider settings={{ reducedMotion: false, lowPower: true, textScale: 1 }}>
      <SpeechToolsProvider controller={v.controller}><VoicePresence placement="floating" /></SpeechToolsProvider></VisualSettingsProvider>);
    expect(presence()?.querySelector("svg")?.getAttribute("data-animate")).toBe("false");
    expect(presence()?.querySelectorAll(".presence-motion")).toHaveLength(0);
    cleanup();
    // The calm screen: no presence at all.
    const f = new Fixture();
    f.startTurn();
    f.text("You don't have to deal with this on your own.");
    f.emit({ type: "notice", notice_id: `ntc_${"9".repeat(26)}`, level: "info", code: "calm_screen", message_key: "safety.calm_screen", params: {}, action: null });
    f.end();
    f.render(<SpeechToolsProvider controller={v.controller}><TutorScreen sessionId={SESSION} /></SpeechToolsProvider>);
    expect(document.querySelector("[data-calm-screen]")).not.toBeNull();
    expect(presence()).toBeNull();
    // Back to the lesson: the presence returns.
    fireEvent.click(screen.getByRole("button", { name: "Back to my lesson when I'm ready" }));
    expect(presence()).not.toBeNull();
  });
});
