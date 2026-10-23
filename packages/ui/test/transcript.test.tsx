// UIA-01, UIA-05, UIA-11 to UIA-15, UXS-03, UXS-04, UXS-19 and LOC-13 for the transcript components.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Profiler, type ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { CLIENT_KEYS, type PartRec } from "@jana/client-core";
import { BASE, SHIPPED, catalogue } from "@jana/i18n";
import { TOOL_NAMES } from "../src/generated/tools.js";
import { LocaleProvider } from "../src/i18n.js";
import { katexCache, renderTex, trust } from "../src/maths/katex.js";
import { MarkdownBlock, StreamingMarkdown } from "../src/markdown/Markdown.js";
import { renderLog, type RenderProps } from "../src/registry/registry.js";
import { StatusLine } from "../src/status/StatusLine.js";
import { defaultRegistry, ToolLine } from "../src/transcript/parts.js";
import { FAMILIES, TOOL_FAMILY } from "../src/transcript/tools.js";
import { Transcript } from "../src/transcript/Transcript.js";
import { TurnView } from "../src/transcript/Turn.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function md(text: string): HTMLElement {
  const { container } = render(<LocaleProvider locale="en"><MarkdownBlock text={text} /></LocaleProvider>);
  return container;
}

describe("UIA-01", () => {
  test("uia01_delta_rerenders_one_part", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    const counts: Record<string, number> = {};
    const registry = defaultRegistry().register<PartRec>("part:text", {
      schema: null,
      renderClass: "card",
      Fallback: () => null,
      Component: ({ data }: RenderProps<PartRec>) => {
        counts[data.part_id] = (counts[data.part_id] ?? 0) + 1;
        return <p>{data.text}</p>;
      },
    });
    const a = f.text("First part.", false);
    const b = f.text("Second part.", false);
    f.render(<TurnView turnId={turnId} />, registry);
    const before = { ...counts };
    f.emit({ type: "text.delta", part_id: b, delta: " More." });
    expect(counts[a]).toBe(before[a]);
    expect(counts[b]).toBe((before[b] ?? 0) + 1);
  });
});

describe("UIA-05", () => {
  test("uia05_optimistic_in_place", () => {
    const f = new Fixture();
    f.render(<Transcript sessionId={SESSION} />);
    const cli = f.send("How high does it rise?");
    const bubble = document.querySelector(`[data-message-key="${cli}"]`);
    expect(bubble).not.toBeNull();
    expect(bubble?.getAttribute("data-state")).toBe("sending");
    f.startTurn(cli); // turn.start and message.accepted
    const after = document.querySelector(`[data-message-key="${cli}"]`);
    expect(after?.getAttribute("data-state")).toBe("accepted");
    expect(after).toBe(bubble); // the same DOM node: replaced in place
  });
});

describe("UIA-11 and UXS-03", () => {
  test("uia11_no_strobe", () => {
    vi.useFakeTimers();
    render(<LocaleProvider locale="en"><ToolLine tool={{ call_id: "c1", name: "math_solve", render_class: "ephemeral", state: { status: "running", title: { pre: "x" } } }} /></LocaleProvider>);
    act(() => vi.advanceTimersByTime(CLIENT_KEYS.ui_running_label_after_ms - 50));
    expect(screen.queryByText("Working it out")).toBeNull();
    act(() => vi.advanceTimersByTime(100));
    expect(screen.queryByText("Working it out")).not.toBeNull();
  });

  test("uxs03_threshold_copy", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    const f = new Fixture();
    const turnId = f.startTurn();
    f.status("waiting_first_token", Date.now());
    f.render(<StatusLine turn={f.holder.getState().turns[turnId]!} />);
    // Every phase of the event contract has copy.
    for (const phase of ["preparing", "queued", "loading_model", "processing_prompt", "waiting_first_token", "streaming", "tool", "checking", "retrying", "compacting"]) {
      expect(BASE).toHaveProperty(`tutor.status.${phase}`);
    }
    act(() => vi.advanceTimersByTime(CLIENT_KEYS.ui_first_token_wait_label_ms + 2_000));
    expect(screen.getByRole("status").textContent).toMatch(/Waiting for the tutor \(5 s\)/);
  });

  test("uxs03_threshold_copy: the faster tutor past the strong tier's threshold, chosen once", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    const f = new Fixture();
    const turnId = f.startTurn();
    f.status("waiting_first_token", Date.now(), "strong");
    let chosen = 0;
    f.render(<StatusLine turn={f.holder.getState().turns[turnId]!} onUseFaster={() => { chosen += 1; }} />);
    act(() => vi.advanceTimersByTime(CLIENT_KEYS.ui_slow_strong_tier_ms - 1_000));
    expect(screen.queryByRole("button", { name: "Use the faster tutor" })).toBeNull();
    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.getByRole("status").textContent).toMatch(/This computer is taking a while\./);
    act(() => screen.getByRole("button", { name: "Use the faster tutor" }).click());
    expect(chosen).toBe(1);
    expect(screen.queryByRole("button", { name: "Use the faster tutor" })).toBeNull();
  });

  test("uxs03_threshold_copy: no faster-tutor offer on the fast tier or without a way to remember it", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    const f = new Fixture();
    const turnId = f.startTurn();
    f.status("waiting_first_token", Date.now(), "fast");
    f.render(<StatusLine turn={f.holder.getState().turns[turnId]!} onUseFaster={() => undefined} />);
    act(() => vi.advanceTimersByTime(CLIENT_KEYS.ui_slow_strong_tier_ms + 1_000));
    expect(screen.queryByRole("button", { name: "Use the faster tutor" })).toBeNull();
  });

  test("uxs03_no_thinking_after_dead", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    const f = new Fixture();
    const turnId = f.startTurn();
    f.status("waiting_first_token", Date.now());
    f.render(<StatusLine turn={f.holder.getState().turns[turnId]!} onStop={() => undefined} onRetry={() => undefined} />);
    act(() => vi.advanceTimersByTime(CLIENT_KEYS.ui_still_working_ms + 1_000));
    expect(screen.getByRole("status").textContent).toMatch(/Still working/);
    act(() => vi.advanceTimersByTime(CLIENT_KEYS.ui_no_reply_ms));
    const text = screen.getByRole("status").textContent ?? "";
    expect(text).toMatch(/No reply from the tutor for 2 min/);
    expect(text).not.toMatch(/Thinking|Waiting/);
    expect(screen.getByRole("button", { name: "Stop" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Try again" })).toBeDefined();
  });

  test("uxs03_no_strobe", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    const f = new Fixture();
    const turnId = f.startTurn();
    f.status("checking", Date.now());
    f.render(<StatusLine turn={f.holder.getState().turns[turnId]!} />);
    act(() => vi.advanceTimersByTime(100));
    expect(screen.getByRole("status").textContent).toBe("");
    act(() => vi.advanceTimersByTime(CLIENT_KEYS.ui_progress_label_after_ms));
    expect(screen.getByRole("status").textContent).toBe("Checking the working");
  });
});

describe("UXS-04", () => {
  test("uxs04_templates_complete", () => {
    for (const name of TOOL_NAMES) expect(FAMILIES).toContain(TOOL_FAMILY[name]);
    for (const locale of SHIPPED) {
      for (const family of FAMILIES) for (const phase of ["running", "done", "failed"]) expect(catalogue(locale)).toHaveProperty(`tool.${family}.${phase}`);
    }
  });

  test("uxs04_run_summary_fold", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    f.tool("math_solve");
    f.tool("math_check_step");
    f.text("Which equation links them?");
    f.render(<TurnView turnId={turnId} />);
    expect(document.querySelectorAll("[data-tool]").length).toBe(2); // while live, each line shows on its own
    f.end();
    expect(screen.getByText("2 checks done")).toBeDefined(); // one run summary once the turn ends
    for (const line of document.querySelectorAll("[data-tool]")) expect(line.closest('[data-open="false"]')).not.toBeNull();
    expect(screen.getByText("Which equation links them?")).toBeDefined(); // cards never fold
  });

  test("a failed check stays outside the fold", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    f.tool("math_solve");
    f.tool("math_check_step", "error");
    f.end();
    f.render(<TurnView turnId={turnId} />);
    expect(screen.getByText("1 check done")).toBeDefined();
    expect(screen.getByText("Couldn't check the working")).toBeDefined();
  });
});

describe("UIA-12", () => {
  test("uia12_boundary_isolates", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    const logs: unknown[] = [];
    const previous = renderLog.current;
    renderLog.current = (record) => logs.push(record);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const registry = defaultRegistry().register<PartRec>("part:text", {
      schema: null,
      renderClass: "card",
      Fallback: ({ data }) => <p>fallback for {(data as PartRec).part_id.slice(0, 4)}</p>,
      Component: ({ data }: RenderProps<PartRec>) => {
        if (data.text.includes("boom")) throw new Error("render failed");
        return <p>{data.text}</p>;
      },
    });
    f.text("Before the broken part.");
    f.text("boom: secret student text");
    f.text("After the broken part.");
    f.end();
    f.render(<TurnView turnId={turnId} />, registry);
    renderLog.current = previous;
    expect(screen.getByText("Before the broken part.")).toBeDefined();
    expect(screen.getByText("After the broken part.")).toBeDefined();
    expect(screen.getByText(/fallback for prt_/)).toBeDefined();
    expect(JSON.stringify(logs)).not.toContain("secret"); // logged by kind and hash, never content
    expect(logs).toHaveLength(1);
  });
});

describe("UIA-13 and UIA-14", () => {
  test("uia13_settled_blocks_stable", () => {
    const words = Array.from({ length: 2000 }, (_, i) => (i % 40 === 39 ? "end.\n\n" : `w${i} `));
    let settled: string[] = [];
    let tail = "";
    const { container, rerender } = render(<LocaleProvider locale="en"><StreamingMarkdown settled={settled} tail={tail} /></LocaleProvider>);
    const seen = new Map<number, Element>();
    const removed: Node[] = [];
    const observer = new MutationObserver((records) => records.forEach((r) => r.removedNodes.forEach((n) => removed.push(n))));
    observer.observe(container, { childList: true, subtree: true });
    let text = "";
    for (const word of words) {
      text += word;
      const blocks = text.split("\n\n");
      tail = blocks.pop() ?? "";
      settled = blocks;
      rerender(<LocaleProvider locale="en"><StreamingMarkdown settled={settled} tail={tail} /></LocaleProvider>);
      const root = container.firstElementChild!;
      settled.forEach((_, i) => {
        const node = root.children[i]!;
        if (!seen.has(i)) seen.set(i, node);
        expect(node).toBe(seen.get(i)); // a settled block keeps its DOM node
      });
    }
    observer.disconnect();
    const settledNodes = new Set(seen.values());
    expect(removed.some((n) => settledNodes.has(n as Element))).toBe(false);
    expect(seen.size).toBeGreaterThan(40);
  });

  test("uia13_html_escaped", () => {
    const container = md('A <script>alert(1)</script> and <img src=x onerror="alert(2)"> here');
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.textContent).toContain("onerror");
  });

  test("uia14_currency_not_math", () => {
    const container = md("Sales of $450 and $300 this month.");
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toBe("Sales of $450 and $300 this month.");
    const maths = md("The speed \\(v^2 = u^2 + 2as\\) and $$s = 10$$");
    expect(maths.querySelectorAll(".katex").length).toBe(2);
  });
});

describe("UIA-15", () => {
  test("uia15_memo_hits", () => {
    const hits = katexCache.hits;
    renderTex("s = \\frac{u^2}{2g}", false);
    renderTex("s = \\frac{u^2}{2g}", false);
    renderTex("s = \\frac{u^2}{2g}", true); // display mode is part of the key
    expect(katexCache.hits - hits).toBe(1);
  });

  test("uia15_trust_restricted", () => {
    expect(trust({ command: "\\htmlClass", class: "changed" })).toBe(true);
    expect(trust({ command: "\\htmlClass", class: "term-a" })).toBe(true);
    expect(trust({ command: "\\htmlClass", class: "anything-else" })).toBe(false);
    expect(trust({ command: "\\href" })).toBe(false);
    expect(trust({ command: "\\includegraphics" })).toBe(false);
    const out = renderTex("\\href{javascript:alert(1)}{x}", false);
    const holder = document.createElement("div");
    holder.innerHTML = "html" in out ? out.html : "";
    expect(holder.querySelector("a, [href], [onclick]")).toBeNull(); // shown as inert text at most
    const bad = renderTex("\\frac{1}{", false);
    expect("error" in bad).toBe(true); // shown as source with keyed copy, never thrown
  });
});

describe("UXS-19", () => {
  test("uxs19_stop_keeps_partial", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    f.text("Let me look at this problem.");
    const live = f.text("The ball rises until", false);
    f.emit({ type: "part.end", part_id: live, status: "interrupted", duration_ms: 1 });
    f.end("interrupted", 6_000);
    f.render(<TurnView turnId={turnId} />);
    expect(screen.getByText("Let me look at this problem.")).toBeDefined();
    expect(screen.getByText("The ball rises until")).toBeDefined();
    expect(f.holder.getState().parts[live]?.status).toBe("interrupted");
    expect(screen.getByText("Stopped after 6 s")).toBeDefined();
  });
});

describe("LOC-13", () => {
  test("loc13_focus_stable_while_streaming", () => {
    const f = new Fixture();
    function Screen({ children }: { children: ReactNode }) {
      return <Profiler id="screen" onRender={() => undefined}>{children}</Profiler>;
    }
    f.render(
      <Screen>
        <Transcript sessionId={SESSION} />
        <textarea aria-label="composer" />
      </Screen>,
    );
    const composer = screen.getByLabelText("composer");
    composer.focus();
    fireEvent.input(composer, { target: { value: "typing" } });
    f.startTurn();
    for (let i = 0; i < 50; i += 1) f.text(`Part ${i} streams in.`);
    f.end();
    expect(document.activeElement).toBe(composer);
  });
});
