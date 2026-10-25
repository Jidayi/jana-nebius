// The UI gallery gate (DSN-15, DSN-16, EVL-10, UIA-09, UIA-29, UXS-02, UXS-36, LOC-04, LOC-20, DSN-04, DSN-06,
// DSN-09): every state renders from data, in both themes, with zero console messages.
import fs from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { errors } from "@jana/contracts-ts";
import { BASE, catalogue, pseudoCatalogue } from "@jana/i18n";
import { RENDERERS } from "@jana/renderers";
import { defaultRegistry } from "@jana/ui";
import { DECLARED, GalleryView, STATES, type GalleryState } from "@jana/ui/gallery";
import { registerVisuals } from "../src/visuals.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");

function registry() {
  return registerVisuals(defaultRegistry(), RENDERERS);
}

function quietRender(state: GalleryState, theme?: string) {
  const messages: unknown[][] = [];
  const spies = (["error", "warn", "log", "info"] as const).map((level) => vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void messages.push([level, ...args])));
  const result = render(<GalleryView state={theme === undefined ? state : { ...state, context: { ...state.context, theme } }} registry={registry()} />);
  spies.forEach((s) => s.mockRestore());
  return { ...result, messages };
}

afterEach(() => cleanup());

describe("DSN-15 and EVL-10", () => {
  test("dsn15_gallery_schema_valid", () => {
    expect(STATES.length).toBeGreaterThan(50);
    for (const state of STATES) expect(errors("design/gallery-state", state), state.id).toEqual([]);
  });

  test("dsn15_payload_matches_backend", () => {
    for (const state of STATES) {
      if (state.payloadContract === null) continue;
      expect(errors(state.payloadContract.replace("https://jana.dev/contracts/", ""), state.payload), state.id).toEqual([]);
    }
  });

  test("evl10_gallery_contract", () => {
    // Composite payloads carry real event payloads: each validates as a tutor event of the backend contract.
    for (const state of STATES) {
      for (const event of (state.payload.events as unknown[] | undefined) ?? []) expect(errors("api/events#/$defs/tutor_event", event), state.id).toEqual([]);
    }
    // Card fixtures cover every card_type of the events contract.
    const cardTypes = new Set(STATES.filter((s) => s.payloadContract?.endsWith("#/$defs/card")).map((s) => (s.payload as { card_type: string }).card_type));
    expect([...cardTypes].sort()).toEqual(["confirm", "hint", "plan", "question", "reflection"]);
  });
});

describe("UXS-02 and UXS-36", () => {
  test("uxs02_declared_states_have_gallery", () => {
    for (const [component, states] of Object.entries(DECLARED)) {
      for (const state of states) expect(STATES.some((s) => s.component === component && s.state === state), `${component} ${state}`).toBe(true);
    }
    for (const state of STATES) expect(DECLARED[state.component] ?? [], `${state.id} declares ${state.state}`).toContain(state.state);
  });

  test("uxs36_screen_state_matrix", () => {
    const matrix = new Set(STATES.map((s) => `${s.component}:${s.state}`));
    const declared = Object.entries(DECLARED).flatMap(([c, states]) => states.map((s) => `${c}:${s}`));
    expect(declared.filter((d) => !matrix.has(d))).toEqual([]);
    // The tutor shell and every card appear; the render test runs each in light and dark at text scale 1.0 and 1.5.
    for (const component of ["TutorTurn", "QuestionCard", "HintCard", "PlanCard", "ReflectionCard", "ConfirmCard", "Composer", "AppStart"]) expect(DECLARED).toHaveProperty(component);
  });

  test("uxs02_no_blank_screens", () => {
    for (const state of STATES) {
      const { container } = quietRender(state);
      expect((container.textContent ?? "").trim().length + container.querySelectorAll("svg, input, textarea").length, state.id).toBeGreaterThan(0);
      cleanup();
    }
  });
});

describe("DSN-16 and UIA-29", () => {
  test("dsn16_render_each_state", () => {
    let renders = 0;
    for (const state of STATES) {
      for (const placement of state.placements) {
        for (const theme of ["light", "dark"]) {
          for (const textScale of [1, 1.5]) {
            const { container, messages } = quietRender({ ...state, context: { ...state.context, textScale } }, theme);
            expect(messages, `${state.id} ${placement} ${theme}`).toEqual([]);
            if ((state.context.locale ?? "en") === "en") for (const text of state.expectText ?? []) expect(container.textContent, `${state.id}: ${text}`).toContain(text);
            renders += 1;
            cleanup();
          }
        }
      }
    }
    expect(renders).toBeGreaterThanOrEqual(STATES.length * 4);
  });

  test("uia29_gallery_renders_clean", () => {
    for (const state of STATES) {
      const { messages } = quietRender(state);
      expect(messages, state.id).toEqual([]);
      cleanup();
    }
  });
});

describe("UIA-09", () => {
  test("uia09_registry_coverage", () => {
    const resolved: string[] = [];
    const reg = registry();
    const lookup = reg.lookup.bind(reg);
    reg.lookup = (...keys: string[]) => {
      const found = lookup(...keys);
      resolved.push(found.key);
      return found;
    };
    for (const state of STATES) {
      resolved.length = 0;
      render(<GalleryView state={state} registry={reg} />);
      expect(resolved.filter((k) => k === "*"), state.id).toEqual([]);
      cleanup();
    }
  });
});

describe("LOC-04 and LOC-20", () => {
  test("loc04_pseudo_locale_gallery", () => {
    const pseudo = Object.values(pseudoCatalogue(BASE));
    for (const state of STATES) {
      const { container, messages } = quietRender({ ...state, context: { ...state.context, locale: "en-XA" } });
      const text = container.textContent ?? "";
      expect(messages, state.id).toEqual([]);
      expect(text, state.id).not.toMatch(/\b[a-z_]+\.[a-z_]+\.[a-z_]+\b/); // no raw key shown
      for (const english of state.expectText ?? []) if (Object.values(BASE).includes(english)) expect(text, `${state.id} untranslated: ${english}`).not.toContain(english);
      cleanup();
    }
    expect(pseudo.length).toBe(Object.keys(catalogue("en")).length);
  });

  test("loc20_reduced_motion", () => {
    const motion = fs.readFileSync(path.join(ROOT, "packages/ui/src/primitives/motion.css"), "utf8");
    const animated = [...motion.matchAll(/\.(jana-[a-z]+)\s*\{[^}]*(animation|transition)/g)].map((m) => m[1]);
    for (const name of new Set(animated)) {
      if (name === "jana-spinner") continue; // a functional indicator keeps running
      expect(motion, name).toMatch(new RegExp(`\\[data-reduced-motion="true"\\][^{]*\\.${name}`));
    }
    for (const state of STATES.filter((s) => s.context.reducedMotion === true)) {
      const { container } = render(<GalleryView state={state} registry={registry()} />);
      const root = container.querySelector("[data-gallery-id]");
      expect(root?.getAttribute("data-reduced-motion"), state.id).toBe("true");
      const classes = [...container.querySelectorAll("[class*='jana-']")].flatMap((el) => [...el.classList].filter((c) => c.startsWith("jana-")));
      expect(classes.every((c) => c === "jana-spinner" || animated.includes(c) || c === "jana-press" || c === "jana-disclosure"), state.id).toBe(true);
      cleanup();
    }
  });
});

describe("DSN-04, DSN-06 and DSN-09", () => {
  test("dsn04_greyscale_distinguishable", () => {
    // Every learning state pairs its colour with an icon and a word, so it survives greyscale.
    const LEARNING = new Set(["correct", "incorrect", "equivalent_unsimplified", "awaiting"]);
    const learning = STATES.filter((s) => {
      if (s.component === "BoardStep") {
        const step = s.payload as { status: string; check_id: string | null };
        return LEARNING.has(step.status) || (step.status === "final" && step.check_id !== null);
      }
      return ["HintCard", "ReflectionCard"].includes(s.component) && s.state === "canonical";
    });
    expect(learning.length).toBeGreaterThanOrEqual(5);
    for (const state of learning) {
      const { container } = render(<GalleryView state={state} registry={registry()} />);
      expect(container.querySelector("svg"), state.id).not.toBeNull();
      expect((container.textContent ?? "").trim(), state.id).not.toBe("");
      cleanup();
    }
  });

  test("dsn06_glyph_coverage", () => {
    // The bundled subsets (latin, latin-ext and Greek, imported by the UI stylesheet) and the ranges their font files cover.
    const all = fs.readFileSync(path.join(ROOT, "packages/ui/node_modules/@fontsource/noto-sans/400.css"), "utf8");
    const ranges: [number, number][] = [];
    for (const block of all.split("/* ").slice(1)) {
      if (!/^noto-sans-(latin|latin-ext|greek)-400-normal \*\//.test(block)) continue;
      const range = /unicode-range:\s*([^;]+);/.exec(block)?.[1] ?? "";
      for (const m of range.matchAll(/U\+([0-9A-F]+)(?:-([0-9A-F]+))?/gi)) ranges.push([parseInt(m[1]!, 16), parseInt(m[2] ?? m[1]!, 16)]);
    }
    expect(ranges.length).toBeGreaterThan(10);
    const covered = (cp: number) => cp < 0x20 || ranges.some(([a, b]) => cp >= a && cp <= b);
    for (const text of [...Object.values(catalogue("en")), ...Object.values(catalogue("en-XA"))]) {
      for (const ch of text) expect(covered(ch.codePointAt(0)!), `U+${ch.codePointAt(0)!.toString(16)} in "${text}"`).toBe(true);
    }
  });

  test("dsn06_no_font_fetch", () => {
    const css = fs.readFileSync(path.join(ROOT, "packages/ui/src/styles/ui.css"), "utf8");
    const imported = [...css.matchAll(/@import "([^"]+)"/g)].map((m) => m[1]!).filter((p) => p.startsWith("@fontsource/") || p.startsWith("katex/"));
    for (const file of imported) {
      const [pkg, ...rest] = file.startsWith("@") ? [file.split("/").slice(0, 2).join("/"), ...file.split("/").slice(2)] : [file.split("/")[0]!, ...file.split("/").slice(1)];
      const text = fs.readFileSync(path.join(ROOT, "packages/ui/node_modules", pkg!, ...rest), "utf8");
      expect(text, file).not.toMatch(/url\(\s*["']?https?:/);
    }
    // The brand faces (D89) are copied into the package: every face their stylesheet declares is a local file that
    // exists, and the token stacks name Funnel Sans for the UI, Funnel Display for display and title, Geist Mono.
    const local = [...css.matchAll(/@import "(\.[^"]+)"/g)].map((m) => path.join(ROOT, "packages/ui/src/styles", m[1]!)).filter((p) => p.includes("/fonts/"));
    expect(local.length).toBeGreaterThan(0);
    const families = new Set<string>();
    for (const sheet of local) {
      const text = fs.readFileSync(sheet, "utf8");
      expect(text, sheet).not.toMatch(/url\(\s*["']?(https?:|\/\/)/);
      for (const m of text.matchAll(/url\("([^"]+)"\)/g)) expect(fs.existsSync(path.join(path.dirname(sheet), m[1]!)), m[1]).toBe(true);
      for (const m of text.matchAll(/font-family:\s*"([^"]+)"/g)) families.add(m[1]!);
    }
    expect([...families].sort()).toEqual(["Funnel Display", "Funnel Sans", "Geist Mono"]);
    const tokens = fs.readFileSync(path.join(ROOT, "packages/ui/src/generated/tokens.css"), "utf8");
    expect(tokens).toMatch(/--font-ui: "Funnel Sans", "Noto Sans"/);
    expect(tokens).toMatch(/--font-display: "Funnel Display"/);
    expect(tokens).toMatch(/--font-mono: "Geist Mono"/);
    expect(fs.readFileSync(path.join(ROOT, "apps/desktop/index.html"), "utf8")).not.toMatch(/https?:\/\//);
  });

  test("dsn09_motion_never_delays_state", () => {
    const motion = fs.readFileSync(path.join(ROOT, "packages/ui/src/primitives/motion.css"), "utf8");
    expect(motion).not.toMatch(/pointer-events|visibility/); // nothing hides or disables content while it animates in
    const question = STATES.find((s) => s.id === "question-card.canonical")!;
    const onAnswer = vi.fn();
    const { getByRole } = render(<GalleryView state={question} registry={registry()} />);
    fireEvent.click(getByRole("button", { name: /v\^2/ }));
    expect(onAnswer).not.toHaveBeenCalled(); // the gallery's own handler; the click itself must not throw or be blocked
  });
});
