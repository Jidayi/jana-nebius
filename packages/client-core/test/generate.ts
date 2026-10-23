// Seeded generators of event sequences for the reducer property tests (UIA-28): a session with turns, parts, deltas,
// tool states, board steps, statuses, cards, resets and unknown events, in a valid order.
import type { Envelope } from "../src/queue.js";

export function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const SESSION = `ses_${"0".repeat(26)}`;
export const EPOCH = "ep_property_test";

let counter = 0;
function id(prefix: string): string {
  counter += 1;
  return `${prefix}_${counter.toString(32).toUpperCase().padStart(26, "0")}`;
}

export function sequence(random: () => number, maxTurns = 3): Envelope[] {
  counter = 0; // ids depend only on the seed, so a failing seed reproduces
  const out: Envelope[] = [];
  let seq = 0;
  const pick = <T>(items: T[]): T => items[Math.floor(random() * items.length)]!;
  const emit = (turnId: string | null, event: Record<string, unknown> & { type: string }) => {
    seq += 1;
    out.push({ v: 1, channel: "session", seq, epoch: EPOCH, session_id: SESSION, turn_id: turnId, ts: 1_000 + seq, event });
  };
  const boardId = id("brd");
  const stepIds: string[] = [];
  const turns = 1 + Math.floor(random() * maxTurns);
  for (let t = 0; t < turns; t += 1) {
    const turnId = id("trn");
    emit(turnId, { type: "turn.start", turn_id: turnId, user_message_id: id("msg"), client_message_id: null, intent: "answer", mode: "guided", fork: false });
    const open: string[] = [];
    let index = 0;
    const steps = 2 + Math.floor(random() * 30);
    for (let s = 0; s < steps; s += 1) {
      const roll = random();
      if (roll < 0.15 || open.length === 0) {
        const partId = id("prt");
        open.push(partId);
        emit(turnId, { type: "part.start", part_id: partId, kind: pick(["text", "text", "tool", "board"]), index });
        index += 1;
      } else if (roll < 0.5) {
        emit(turnId, { type: "text.delta", part_id: pick(open), delta: pick(["The ", "ball ", "rises\n\n", "$450 ", "\\(v^2\\) ", "", "**bold"]) });
      } else if (roll < 0.55) {
        emit(turnId, { type: "text.reset", part_id: pick(open), reason: "regenerating" });
      } else if (roll < 0.62) {
        const toolPart = pick(open);
        emit(turnId, { type: "tool.state", part_id: toolPart, call_id: `${toolPart}_call_${Math.floor(random() * 3)}`, name: "math_solve", render_class: "ephemeral", state: { status: pick(["pending", "running", "completed"]) } });
      } else if (roll < 0.7) {
        emit(turnId, { type: "status", phase: pick(["preparing", "waiting_first_token", "tool", "checking", "streaming"]), label_key: null, progress: null, phase_started_ts: 1_000 + seq, model_tier: "fast" });
      } else if (roll < 0.78) {
        if (stepIds.length === 0 || random() < 0.4) stepIds.push(id("stp"));
        const stepId = pick(stepIds);
        emit(turnId, { type: "board.step", board_id: boardId, step_id: stepId, index: stepIds.indexOf(stepId), latex: `x = ${Math.floor(random() * 9)}`, reason: null, owner: pick(["tutor", "student"]), status: pick(["draft", "final", "awaiting", "correct"]), check_id: null, error: null });
      } else if (roll < 0.8 && stepIds.length > 0) {
        emit(turnId, { type: "board.await", board_id: boardId, step_id: pick(stepIds), prompt: "Your turn", input_kind: "latex" });
      } else if (roll < 0.84) {
        const partId = pick(open);
        emit(turnId, { type: "card.open", request_id: id("req"), part_id: partId, call_id: null, card: { card_type: "question", prompt: "Which?", options: [], allow_free_text: true, multi: false } });
      } else if (roll < 0.86) {
        emit(turnId, { type: "future.thing", payload: [1, 2] });
      } else if (roll < 0.88) {
        emit(turnId, { type: "session.updated", title: `Problem ${seq}` });
      } else {
        const partId = open.splice(Math.floor(random() * open.length), 1)[0]!;
        emit(turnId, { type: "part.end", part_id: partId, status: pick(["complete", "complete", "interrupted", "error"]), duration_ms: 5 });
      }
    }
    for (const partId of open) emit(turnId, { type: "part.end", part_id: partId, status: "complete", duration_ms: 5 });
    emit(turnId, { type: "turn.end", status: "complete", stop_reason: "completed", elapsed_ms: 10, usage: null, verification: "not_applicable", persisted: { message_id: id("msg"), part_ids: [] }, degraded: false, degraded_reason: null });
  }
  return out;
}
