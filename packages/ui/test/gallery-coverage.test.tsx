// UXS-34 and UXS-36 for the stage 3 screens: every voice state of TABLE VOC-04 and every microphone error of VOC-16
// has a voice bar gallery state with its own words, and the screens built on direction A have their states as data.
import { readFileSync } from "node:fs";
import path from "node:path";
import { cleanup, render, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { errors } from "@jana/contracts-ts";
import { BASE } from "@jana/i18n";
import { GalleryView, STATES } from "../gallery/index.js";

afterEach(() => cleanup());

const VOICE_STATES = ["idle", "listening", "thinking", "speaking", "interrupted", "unavailable"];
const MICROPHONE = ["voice.microphone_unavailable", "voice.microphone_missing", "voice.microphone_denied", "voice.too_noisy"];

describe("UXS-34", () => {
  test("uxs34_voice_states_gallery", () => {
    const bars = STATES.filter((s) => s.component === "VoiceBar");
    for (const voice of VOICE_STATES) {
      const state = bars.find((s) => (s.payload as { state: string }).state === voice);
      expect(state, voice).toBeDefined();
      const { container } = render(<GalleryView state={state!} />);
      expect(container.textContent, voice).toContain(BASE[`voice.state.${voice}`]);
      cleanup();
    }
    // Each microphone error has its own state and words, and the bar keeps the way to type (no input is disabled).
    for (const reason of MICROPHONE) {
      const state = bars.find((s) => (s.payload as { reason: string | null }).reason === reason);
      expect(state, reason).toBeDefined();
      const { container } = render(<GalleryView state={state!} />);
      expect(container.textContent, reason).toContain(BASE[reason]);
      expect(container.querySelectorAll("button:disabled, select:disabled")).toHaveLength(0);
      cleanup();
    }
  });
});

describe("UXS-36", () => {
  test("test_uxs36_stage3_screens_have_states", () => {
    const has = (component: string, state: string, variant?: string) => STATES.some((s) => s.component === component && s.state === state && (variant === undefined || s.variant === variant));
    // Practice: a question, marked tries, loading, empty, could not start, not served (UXS-24, API-27).
    for (const [state, variant] of [["canonical", undefined], ["canonical", "tries"], ["loading"], ["empty"], ["error-retriable"], ["error-final", "not-served"]] as const) expect(has("Practice", state, variant), `Practice ${state}`).toBe(true);
    // The calm screen with and without a verified helpline (UXS-43); the left rail full and collapsed (UXS-01, DSN-25).
    expect(has("CalmScreen", "canonical") && has("CalmScreen", "empty")).toBe(true);
    expect(has("LeftRail", "canonical") && has("LeftRail", "canonical", "rail")).toBe(true);
    // The picker's empty and unreadable states (UXS-09) and recovery's steps (UXS-47).
    for (const state of ["canonical", "empty", "loading", "error-final"]) expect(has("ProfilePicker", state), state).toBe(true);
    for (const state of ["canonical", "loading", "error-retriable"]) expect(has("ProfileRecovery", state), state).toBe(true);
  });
});

test("uxs16_status_table_complete", () => {
  const contract = JSON.parse(readFileSync(path.resolve(import.meta.dirname, "../../../docs/specification/contracts/api/events.schema.json"), "utf8")).$defs.board_step_status.enum as string[];
  const expected: Record<string, { owners: string[]; text: string }> = {
    draft: { owners: ["tutor"], text: "Draft" }, final: { owners: ["tutor"], text: "Shown by the tutor" },
    awaiting: { owners: ["student"], text: "Your turn" }, checking: { owners: ["student", "tutor"], text: "Checking" },
    correct: { owners: ["student"], text: "Checked" }, incorrect: { owners: ["student"], text: "Not quite" },
    equivalent_unsimplified: { owners: ["student"], text: "Right, can be simplified" }, unchecked: { owners: ["student", "tutor"], text: "Not checked" },
  };
  expect([...contract].sort()).toEqual(Object.keys(expected).sort());
  for (const status of contract) for (const owner of expected[status]!.owners) {
    const state = STATES.find((s) => s.component === "BoardStep" && s.payload.status === status && s.payload.owner === owner);
    expect(state, `${status}/${owner}`).toBeDefined();
    expect(errors("api/events#/$defs/ev_board_step", state!.payload)).toEqual([]);
    const { container } = render(<GalleryView state={state!} />);
    const row = container.querySelector(`li[data-status="${status}"]`)!;
    expect(row.textContent).toContain(status === "checking" && owner === "student" ? "Checking your line…" : expected[status]!.text);
    expect(row.getAttribute("aria-label")).toContain(expected[status]!.text);
    if (status === "final" && state!.payload.check_id) expect(row.querySelector("[data-check-id] svg")).not.toBeNull();
    if (status === "incorrect") expect(row.textContent?.toLowerCase()).not.toContain("wrong");
    if (status === "unchecked" && owner === "tutor") expect(row.textContent).not.toMatch(/=\s*\d/);
    cleanup();
  }
});

test.each(["unsure", "disagreement", "beyond-level", "off-topic", "distress", "content-only", "low-battery", "restarting", "crashed", "cannot-run"])("uxs20_special_state_copy: %s", (variant) => {
  const state = STATES.find((s) => s.id === `tutor-special.canonical.${variant}`);
  expect(state).toBeDefined();
  expect(state!.expectText!.length).toBeGreaterThan(0);
  const events = state!.payload.events as Record<string, unknown>[] | undefined;
  for (const event of events ?? []) expect(errors("api/events", { v: 1, channel: "session", seq: 1, epoch: "ep_special", session_id: `ses_${"0".repeat(26)}`, turn_id: `trn_${"1".repeat(26)}`, ts: 1, event })).toEqual([]);
  const { container } = render(<GalleryView state={state!} />);
  for (const text of state!.expectText!) expect(container.textContent, `${variant}: ${text}`).toContain(text);
  for (const label of variant === "unsure" ? ["Open lesson"] : variant === "beyond-level" ? ["Open topic"] : variant === "crashed" ? ["Try again"] : variant === "cannot-run" ? ["Open lessons"] : []) {
    expect(within(container).getByRole("button", { name: label })).toBeDefined();
  }
});
