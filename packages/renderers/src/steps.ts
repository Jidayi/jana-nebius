// Step operations (VSL-10): step n shows the cumulative state of steps 0…n, recomputed from step 0 every time (Back
// is a recomputation, never an inverse operation). highlight replaces the previous step's set; reveal shows parts
// declared hidden at first; hide removes parts and their labels; add brings in derived elements the resolution
// computed. Step -1 is the visual before its first step.
import type { ResolvedSpec } from "./contract.js";

export interface StepState {
  highlight: Set<string>;
  hidden: Set<string>;
  revealed: Set<string>;
  added: { element: string; of?: string }[];
  boardStep: string | null;
}

interface Step {
  highlight?: string[];
  reveal?: string[];
  hide?: string[];
  add?: { element: string; of?: string }[];
  board_step?: string;
}

export function stepCount(spec: ResolvedSpec): number {
  return ((spec.steps as Step[] | undefined) ?? []).length;
}

export function stepState(spec: ResolvedSpec, step: number): StepState {
  const steps = (spec.steps as Step[] | undefined) ?? [];
  const state: StepState = { highlight: new Set(), hidden: new Set(), revealed: new Set(), added: [], boardStep: null };
  const last = Math.min(step, steps.length - 1);
  for (let n = 0; n <= last; n += 1) {
    const s = steps[n] ?? {};
    if (s.highlight !== undefined) state.highlight = new Set(s.highlight);
    for (const id of s.reveal ?? []) {
      state.revealed.add(id);
      state.hidden.delete(id);
    }
    for (const id of s.hide ?? []) state.hidden.add(id);
    for (const a of s.add ?? []) state.added.push(a.of === undefined ? { element: a.element } : { element: a.element, of: a.of });
    state.boardStep = s.board_step ?? state.boardStep;
  }
  return state;
}

/** The step bound to a board step (VSL-20), or null when no step binds it. */
export function stepForBoard(spec: ResolvedSpec, boardStepId: string): number | null {
  const steps = (spec.steps as Step[] | undefined) ?? [];
  const index = steps.findIndex((s) => s.board_step === boardStepId);
  return index < 0 ? null : index;
}

/** Whether an element derived by `add` is shown at this state. */
export function isAdded(state: StepState, element: string, of?: string): boolean {
  return state.added.some((a) => a.element === element && (of === undefined || a.of === of));
}
