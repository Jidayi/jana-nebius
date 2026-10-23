// DSN-25: the product's name and mark appear only in their fixed placements (the launch screen, the top of the left
// rail, the profile picker and first run's "Who's learning?", Settings → About, the header of printed reports); the
// interface, the board and the tutor's lines never show
// the brand. A crawl of every gallery state, in every locale the gallery renders, finds the mark nowhere else.
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { BASE } from "@jana/i18n";
import { RENDERERS } from "@jana/renderers";
import { BRAND_PLACEMENTS, defaultRegistry } from "@jana/ui";
import { GalleryView, STATES } from "@jana/ui/gallery";
import { registerVisuals } from "../src/visuals.js";

afterEach(() => cleanup());

const NAME = BASE["app.name"] ?? "";
const allowed = new Set<string>(BRAND_PLACEMENTS);

describe("DSN-25", () => {
  test("dsn25_brand_placements", () => {
    expect(NAME.length).toBeGreaterThan(0);
    const seen: string[] = [];
    for (const state of STATES) {
      const { container } = render(<GalleryView state={state} registry={registerVisuals(defaultRegistry(), RENDERERS)} />);
      // The tutor's own name, Jana by default, is not a brand placement (DSN-25, D105): words marked as naming the
      // tutor (its turns' label, Settings → Tutor, the pick) are left out of the crawl.
      const shown = container.cloneNode(true) as HTMLElement;
      // AppShell composes the sanctioned LeftRail placement. Check the rail's location, then crawl the rest
      // of the shell as an ordinary interface; the shell itself is not an additional brand placement.
      if (["AppShell", "TutorScreen"].includes(state.component)) {
        expect(shown.querySelectorAll('[data-region="sidebar"] [data-brand]').length).toBe(1);
        shown.querySelector('[data-region="sidebar"]')?.remove();
      }
      const marks = shown.querySelectorAll("[data-brand]").length;
      for (const el of shown.querySelectorAll("[data-tutor-name]")) el.remove();
      const named = new RegExp(`\\b${NAME}\\b`).test(shown.textContent ?? "");
      if (marks > 0 || named) {
        seen.push(state.component);
        expect(allowed.has(state.component), `${state.id} shows the brand outside its placements`).toBe(true);
      }
      cleanup();
    }
    // The launch screen carries the mark; no catalogue string other than the name itself (and the Jana character's
    // default name, the tutor's, D105) names the product.
    expect(seen).toContain("AppStart");
    const own = new Set(["app.name", "brand.mark", "tutor.character.jana.name"]);
    const naming = Object.entries(BASE).filter(([key, text]) => !own.has(key) && new RegExp(`\\b${NAME}\\b`).test(text));
    expect(naming).toEqual([]);
  });
});
