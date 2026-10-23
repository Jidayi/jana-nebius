// VSL-02 when rendering: the client draws only kinds its renderers know; any other `type` takes the words fallback
// (VSL-16) through the same registry the app wires, without an exception or a console message. Specs are synthetic.
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { StoreHolder, emptyStore, hydrate, reduce, type CoreSnapshot, type Envelope } from "@jana/client-core";
import { RENDERERS } from "@jana/renderers";
import { LocaleProvider, PartView, RegistryProvider, StoreProvider, defaultRegistry } from "@jana/ui";
import { registerVisuals } from "../src/visuals.js";

const SESSION = `ses_${"0".repeat(26)}`;
const EPOCH = "ep_visual_tests";
const TURN = `trn_${"0".repeat(25)}1`;
const PART = `prt_${"0".repeat(25)}1`;
const VISUAL = `vis_${"0".repeat(25)}1`;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function snapshot(): CoreSnapshot {
  return {
    session: { session_id: SESSION, title: "", mode: "guided", subject: "biology", topic_id: null, created_ts: 0, updated_ts: 0, archived: false },
    cursor: { epoch: EPOCH, seq: 0 },
    messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null,
  };
}

function resolved(type: string, params: Record<string, unknown>): Record<string, unknown> {
  return {
    spec_version: 1, type, params, numbers_from: [], steps: [], labels: "shown", visual_id: VISUAL, status: "ok", parts: [],
    alt: { summary: "A labelled heart with four chambers.", steps: [], locale: "en" }, computed: {}, repairs: [],
  };
}

/** A store fed the events of one visual part, as the session controller feeds it. */
function holderWith(spec: Record<string, unknown>): StoreHolder {
  const holder = new StoreHolder();
  holder.update(() => hydrate(emptyStore(), snapshot()));
  const events = [
    { type: "part.start", part_id: PART, kind: "visual", index: 0 },
    { type: "visual.spec", visual_id: VISUAL, part_id: PART, spec },
    { type: "part.end", part_id: PART, status: "complete", duration_ms: 1 },
  ];
  events.forEach((event, i) => {
    const envelope: Envelope = { v: 1, channel: "session", seq: i + 1, epoch: EPOCH, session_id: SESSION, turn_id: TURN, ts: 0, event };
    holder.update((s) => reduce(s, envelope));
  });
  return holder;
}

function quietRender(spec: Record<string, unknown>) {
  const messages: unknown[][] = [];
  for (const level of ["error", "warn", "log", "info"] as const) vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void messages.push([level, ...args]));
  const registry = registerVisuals(defaultRegistry(), RENDERERS);
  const resolvedKeys: string[] = [];
  const lookup = registry.lookup.bind(registry);
  registry.lookup = (...keys: string[]) => {
    const found = lookup(...keys);
    resolvedKeys.push(found.key);
    return found;
  };
  const { container } = render(
    <LocaleProvider locale="en">
      <RegistryProvider registry={registry}>
        <StoreProvider holder={holderWith(spec)} session={null}>
          <PartView partId={PART} />
        </StoreProvider>
      </RegistryProvider>
    </LocaleProvider>,
  );
  return { container, messages, resolvedKeys };
}

describe("VSL-02", () => {
  test("vsl02_unknown_kind_fallback", () => {
    expect(RENDERERS.map((r) => r.kind)).not.toContain("heart_3d");
    let result: ReturnType<typeof quietRender> | undefined;
    expect(() => {
      result = quietRender(resolved("heart_3d", { chambers: 4, rotate: true }));
    }).not.toThrow();
    const { container, messages, resolvedKeys } = result!;
    // No renderer is registered for the kind, so the lookup lands on the visual words fallback, not a drawing.
    expect(resolvedKeys).toEqual(["visual:*"]);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).toContain("A labelled heart with four chambers.");
    expect(messages).toEqual([]);

    // The same client draws a kind it has a renderer for, so the fallback above is the kind check, not a broken view.
    cleanup();
    const known = quietRender(resolved("function_graph", { curves: [{ id: "c", expr: "x^2" }], x_range: [-2, 2] }));
    expect(known.resolvedKeys).toEqual(["visual:function_graph"]);
    expect(known.container.querySelector("svg")).not.toBeNull();
    expect(known.messages).toEqual([]);
  });
});
