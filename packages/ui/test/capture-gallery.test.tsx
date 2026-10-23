import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Fixture } from "./harness.js";
import { StoreProvider } from "../src/store.js";
import { PhotoCapture } from "../src/composer/PhotoCapture.js";
import { LocaleProvider } from "../src/i18n.js";
import type { CapturedQuestion } from "@jana/client-core";
import { errors } from "@jana/contracts-ts";
import { GalleryView, STATES } from "../gallery/index.js";

const variants = ["camera-live", "camera-still", "camera-light", "camera-missing", "camera-blocked", "camera-busy", "outline-found", "no-outline", "corner-focused", "preprocessing", "quality-advisory", "quality-blocking", "unreadable", "question-picker", "subparts", "up-next"];
afterEach(() => { cleanup(); vi.useRealTimers(); });
test.each(["light", "dark"])("uxs45_capture_states_gallery: %s", async (theme) => {
  vi.useFakeTimers();
  for (const variant of variants) {
    const state = STATES.find((s) => s.component === "PhotoCapture" && s.variant === variant)!;
    expect(state, variant).toBeDefined();
    expect(state.expectText!.length, variant).toBeGreaterThan(0);
    expect(errors("input/captured-question", state.payload), variant).toEqual([]);
    const { container } = render(<GalleryView state={{ ...state, context: { ...state.context, theme } }} />);
    for (const text of state.expectText!) expect(container.textContent, `${variant}: ${text}`).toContain(text);
    if (variant === "corner-focused") expect(document.activeElement?.getAttribute("aria-label")).toBe("Crop corner 1");
    if (variant === "no-outline") expect(container.querySelectorAll("button[aria-description]")).toHaveLength(4);
    if (variant === "quality-blocking") expect(within(container).queryByRole("button", { name: "Use this photo anyway" })).toBeNull();
    if (["question-picker", "subparts", "up-next"].includes(variant)) {
      expect(within(container).getAllByRole("radio")).toHaveLength(2);
      expect(within(container).getByRole("button", { name: "Yes, that's it" })).toHaveProperty("disabled", true);
      fireEvent.click(within(container).getAllByRole("radio")[0]!);
      expect(container.textContent).toContain("Up next");
      expect(container.querySelector(".tiptap")?.textContent).toContain("Explain your answer.");
      expect(within(container).getByRole("button", { name: "Yes, that's it" })).toHaveProperty("disabled", false);
    }
    cleanup();
  }
});

test.each(["light", "dark"])("inp27_photo_injection_inert: auxiliary-field removals are visible in %s", (theme) => {
  const state = STATES.find((s) => s.id === "photo-capture.canonical.awaiting-confirmation")!;
  const injected = { ...state, context: { ...state.context, theme }, payload: { ...state.payload, injection: { flagged: true, spans_removed: 1 } } };
  const { container } = render(<GalleryView state={injected} />);
  expect(within(container).getByRole("status").textContent).toBe("[instruction-like text removed]");
  expect(container.textContent).toContain("Is this the question?");
});


test("a new preprocessing transition waits the full 300 ms before showing the indicator", async () => {
  vi.useFakeTimers();
  const state = STATES.find((s) => s.component === "PhotoCapture" && s.variant === "preprocessing");
  expect(state).toBeDefined();
  const { container } = render(<LocaleProvider locale="en"><StoreProvider holder={new Fixture().holder} session={null}><PhotoCapture sessionId="ses_test" purpose="question" previewCapture={state?.payload as unknown as CapturedQuestion} onConfirmed={() => undefined} onTyped={() => undefined} onClose={() => undefined} /></StoreProvider></LocaleProvider>);
  expect(container.textContent).not.toContain("Reading your photo…");
  await act(async () => { vi.advanceTimersByTime(299); }); expect(container.textContent).not.toContain("Reading your photo…");
  await act(async () => { vi.advanceTimersByTime(1); }); expect(container.textContent).toContain("Reading your photo…");
});
