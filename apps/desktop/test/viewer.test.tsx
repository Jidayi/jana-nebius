// The visual viewer in the app (UIA-20) and step syncing with the board (VSL-20), with the vetted renderers wired in
// through the registry as the app wires them. Specs are the engine-resolved fixtures of the renderer package.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { CLIENT_KEYS, StoreHolder, emptyStore, hydrate, reduce, selectBoardLine, type CoreSnapshot, type Envelope } from "@jana/client-core";
import { RENDERERS } from "@jana/renderers";
import { Board, LocaleProvider, PartView, RegistryProvider, StoreProvider, defaultRegistry } from "@jana/ui";
import { registerVisuals } from "../src/visuals.js";

const SESSION = `ses_${"0".repeat(26)}`;
const EPOCH = "ep_viewer_tests";
const TURN = `trn_${"0".repeat(25)}1`;
const PART = `prt_${"0".repeat(25)}1`;
const BOARD = `brd_${"0".repeat(25)}1`;
const FIXTURES = path.resolve(import.meta.dirname, "../../../packages/renderers/fixtures/visuals");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function fixture(id: string): Record<string, unknown> {
  return (JSON.parse(fs.readFileSync(path.join(FIXTURES, `${id}.json`), "utf8")) as { spec: Record<string, unknown> }).spec;
}

function snapshot(): CoreSnapshot {
  return {
    session: { session_id: SESSION, title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false },
    cursor: { epoch: EPOCH, seq: 0 }, messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null,
  };
}

function holderWith(spec: Record<string, unknown>, boardLines: string[] = []): StoreHolder {
  const holder = new StoreHolder();
  holder.update(() => hydrate(emptyStore(), snapshot()));
  const events: Record<string, unknown>[] = [
    ...(boardLines.length > 0 ? [{ type: "board.reset", board_id: BOARD, part_id: PART, problem: null }] : []),
    ...boardLines.map((step_id, index) => ({ type: "board.step", board_id: BOARD, step_id, index, latex: `x_{${index}}`, reason: null, owner: "tutor", status: "final", check_id: null, error: null })),
    { type: "part.start", part_id: PART, kind: "visual", index: 0 },
    { type: "visual.spec", visual_id: spec.visual_id, part_id: PART, spec },
    { type: "part.end", part_id: PART, status: "complete", duration_ms: 1 },
  ];
  events.forEach((event, i) => {
    const envelope: Envelope = { v: 1, channel: "session", seq: i + 1, epoch: EPOCH, session_id: SESSION, turn_id: String(event.type).startsWith("board.") ? null : TURN, ts: 0, event } as Envelope;
    holder.update((s) => reduce(s, envelope));
  });
  return holder;
}

function quiet() {
  const messages: unknown[][] = [];
  for (const level of ["error", "warn", "log", "info"] as const) vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void messages.push([level, ...args]));
  return messages;
}

function mount(holder: StoreHolder, withBoard = false) {
  const registry = registerVisuals(defaultRegistry(), RENDERERS);
  return render(
    <LocaleProvider locale="en">
      <RegistryProvider registry={registry}>
        <StoreProvider holder={holder} session={null}>
          <PartView partId={PART} />
          {withBoard && <Board sessionId={SESSION} />}
        </StoreProvider>
      </RegistryProvider>
    </LocaleProvider>,
  );
}

describe("UIA-20", () => {
  test("uia20_client_revalidation_fallback", () => {
    const good = fixture("free-body");
    // The envelope is fine, but the params fail the kind's schema on the client: no forces, an unknown object.
    const bad = { ...good, params: { object: "spaceship", forces: [] } };
    const messages = quiet();
    let view: ReturnType<typeof mount> | undefined;
    expect(() => {
      view = mount(holderWith(bad));
    }).not.toThrow();
    const { container } = view!;
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).toContain((good.alt as { summary: string }).summary);
    expect(messages).toEqual([]);
    // A kind whose params schema is the renderer's own passes the envelope check and is caught by the viewer's
    // re-validation of the params (VSL-15 stage 4 again on the client).
    cleanup();
    const venn = fixture("venn-diagram");
    const odd = mount(holderWith({ ...venn, params: { ...(venn.params as object), sets: [{ id: "Z", label: "Nowhere" }] } }));
    expect(odd.container.querySelector("[data-visual-viewer='fallback']")).not.toBeNull();
    expect(odd.container.querySelector("svg")).toBeNull();
    expect(odd.container.textContent).toContain((venn.alt as { summary: string }).summary);
    expect(messages).toEqual([]);
    // The same viewer draws the valid spec, with its step controls and the alt-text disclosure.
    cleanup();
    const ok = mount(holderWith(good));
    expect(ok.container.querySelector("[data-kind='free_body']")).not.toBeNull();
    expect(ok.getByText("Next step")).toBeTruthy();
    expect(ok.getByText("Describe this diagram")).toBeTruthy();
  });
});

describe("UIA-20 gallery", () => {
  test("every visual viewer state draws its kind (or, for error-final, the words)", async () => {
    const { GalleryView, STATES } = await import("@jana/ui/gallery");
    const registry = registerVisuals(defaultRegistry(), RENDERERS);
    const states = STATES.filter((s) => s.component === "VisualViewer");
    expect(states.length).toBeGreaterThan(80);
    for (const state of states) {
      const { container } = render(<GalleryView state={state} registry={registry} />);
      const kind = String(state.payload.type);
      if (state.state === "error-final") {
        expect(container.querySelector(`[data-kind='${kind}']`), state.id).toBeNull();
        expect(container.textContent, state.id).toContain((state.payload.alt as { summary: string }).summary);
      } else expect(container.querySelector(`[data-kind='${kind}']`), state.id).not.toBeNull();
      cleanup();
    }
  });
});

describe("VSL-20", () => {
  test("vsl20_board_drives_visual", () => {
    const spec = fixture("free-body"); // steps bound to stp_01, stp_02 and stp_03
    const holder = holderWith(spec, ["stp_01", "stp_02"]);
    const { container } = mount(holder, true);
    const shownStep = () => Number(container.querySelector("[data-visual-step]")?.getAttribute("data-visual-step"));
    expect(shownStep()).toBe(1); // the newest board line, stp_02, is the visual's step 2
    // Back on the board: the visual follows to the bound step.
    act(() => holder.update((s) => selectBoardLine(s, BOARD, "stp_01")));
    expect(shownStep()).toBe(0);
    act(() => holder.update((s) => selectBoardLine(s, BOARD, "stp_02")));
    expect(shownStep()).toBe(1);
    // The board moves from step 2 to step 3 (a new line from the tutor): the visual is at its step 3 within budget.
    const start = performance.now();
    act(() => {
      const envelope = { v: 1, channel: "session", seq: 99, epoch: EPOCH, session_id: SESSION, turn_id: null, ts: 0,
        event: { type: "board.step", board_id: BOARD, step_id: "stp_03", index: 2, latex: "x_{2}", reason: null, owner: "tutor", status: "final", check_id: null, error: null } } as Envelope;
      holder.update((s) => reduce(s, envelope));
    });
    const elapsed = performance.now() - start;
    expect(shownStep()).toBe(2);
    expect(elapsed).toBeLessThanOrEqual(CLIENT_KEYS.visual_step_sync_ms);
    // An unbound line leaves the visual where it is.
    act(() => {
      const envelope = { v: 1, channel: "session", seq: 100, epoch: EPOCH, session_id: SESSION, turn_id: null, ts: 0,
        event: { type: "board.step", board_id: BOARD, step_id: "stp_04", index: 3, latex: "x_{3}", reason: null, owner: "tutor", status: "final", check_id: null, error: null } } as Envelope;
      holder.update((s) => reduce(s, envelope));
    });
    expect(shownStep()).toBe(2);
  });

  test("vsl20_visual_drives_board", () => {
    const spec = fixture("free-body");
    const holder = holderWith(spec, ["stp_01", "stp_02", "stp_03"]);
    const { container } = mount(holder, true);
    expect(Number(container.querySelector("[data-visual-step]")?.getAttribute("data-visual-step"))).toBe(2);
    // The student steps the visual back twice, to its step 1: the bound board line is highlighted.
    const visual = within(container.querySelector<HTMLElement>("[data-visual-viewer]")!);
    fireEvent.click(visual.getByRole("button", { name: "Previous step" }));
    fireEvent.click(visual.getByRole("button", { name: "Previous step" }));
    expect(Number(container.querySelector("[data-visual-step]")?.getAttribute("data-visual-step"))).toBe(0);
    const line = container.querySelector("li[data-step-id='stp_01']");
    expect(line?.getAttribute("data-highlighted")).toBe("true");
    expect(line?.getAttribute("aria-current")).toBe("step");
    expect(container.querySelector("li[data-step-id='stp_03']")?.getAttribute("data-highlighted")).toBeNull();
    expect(holder.getState().boards[BOARD]?.current).toBe("stp_01");
  });
});


test("diagram alternatives open the same part without revealing hidden names", () => {
  const spec = fixture("balanced-equation");
  const parts = (spec.parts as { id: string; name: string; focusable: boolean }[]).filter((p) => p.focusable);
  const { getByRole, container } = mount(holderWith(spec));
  const select = getByRole("combobox", { name: "Choose a diagram part" }) as HTMLSelectElement;
  expect(JSON.parse(select.dataset.partEquivalents!)).toEqual(parts.map((p) => p.id));
  fireEvent.change(select, { target: { value: parts[0]!.id } });
  expect(container.querySelector("[data-visual-part-panel]")?.getAttribute("data-visual-part-panel")).toBe(parts[0]!.id);
  fireEvent.click(getByRole("button", { name: "Hide labels" }));
  expect([...select.options].slice(1).map((o) => o.text)).toEqual(parts.map((_, i) => `Part ${i + 1} of ${parts.length}, label hidden`));
  const panel = container.querySelector("[data-visual-part-panel]");
  expect(panel?.getAttribute("aria-label")).toBe(`Part 1 of ${parts.length}, label hidden`);
  expect(panel?.textContent).not.toContain(parts[0]!.name);
});

test("spoken names include the visible computed equation labels", () => {
  const { container } = mount(holderWith(fixture("balanced-equation")));
  const parts = [...container.querySelectorAll('[data-part][role="button"]')];
  expect(parts.length).toBeGreaterThan(0);
  for (const part of parts) {
    const visible = part.textContent?.replace(/\s+/g, " ").trim();
    if (visible) expect(part.getAttribute("aria-label")).toContain(visible);
  }
});


test("every interactive visual part includes its rendered text in its spoken name", async () => {
  const { GalleryView, STATES } = await import("@jana/ui/gallery");
  const registry = registerVisuals(defaultRegistry(), RENDERERS);
  for (const state of STATES.filter((s) => ["VisualViewer", "FunctionGraph"].includes(s.component))) {
    const { container } = render(<GalleryView state={state} registry={registry} />);
    for (const part of container.querySelectorAll('[data-part][role="button"]')) {
      const visible = part.textContent?.replace(/\s+/g, " ").trim();
      if (visible) expect(part.getAttribute("aria-label"), `${state.id} ${part.getAttribute("data-part")}`).toContain(visible);
    }
    cleanup();
  }
});
