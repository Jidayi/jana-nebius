// The normalised client store (UIA-01): a delta touches one record, so one component re-renders. Components select
// records by id; no component subscribes to a whole slice. The store holds the unlocked profile's data only.
import type { Card, ContentBlock, EvStatus, StepError, Usage, VisualsVisualSpecResolved } from "@jana/contracts-ts";
import type { ConnectionState } from "./stream/client.js";

export type { ConnectionState };

export interface ConnectionSlice {
  state: ConnectionState;
  epoch: string | null;
  last_seq: number;
  retry_at: number | null;
  lagging: boolean;
  /** Set when the core's epoch differs from the cursor's or a cursor expired: reload the snapshot (API-17). */
  resync: boolean;
  /** Server time minus local time, estimated from envelope `ts` (UIA-22). */
  clock_offset_ms: number;
  /** "Reconnecting to the tutor…": only after the outage threshold, or while resyncing (UIA-07). */
  banner: boolean;
  /** Server time of the last event received: silence thresholds count from it (UXS-02, UXS-03). */
  last_event_ts: number | null;
}

export interface SessionRec {
  session_id: string;
  title: string;
  mode: string;
  subject: string;
  topic_id: string | null;
  created_ts: number;
  updated_ts: number;
  archived: boolean;
  turn_ids: string[];
  board_ids: string[];
  hint_rung: number;
  /** Optimistic messages not yet accepted, in the order they were sent (UIA-05). */
  pending_ids: string[];
}

/** A status phase; `unknown` is a phase from a newer core that this build does not know (API-35 open enum). */
export type Phase = Omit<EvStatus, "type" | "phase"> & { phase: EvStatus["phase"] | "unknown" };

export interface TurnRec {
  turn_id: string;
  session_id: string;
  intent: string;
  mode: string;
  user_message_id: string | null;
  client_message_id: string | null;
  status: "streaming" | "complete" | "error" | "interrupted" | "truncated";
  stop_reason: string | null;
  degraded: boolean;
  degraded_reason: string | null;
  error: { code: string; message: string; retryable: boolean; scope: string } | null;
  part_ids: string[];
  message_id: string | null;
  phase: Phase | null;
  usage: Usage | null;
  elapsed_ms: number | null;
  verification: string | null;
  hint_rung: number | null;
  ts: number;
}

export interface MessageRec {
  /** The client id when the message has one, so the optimistic bubble keeps its component (UIA-05). */
  key: string;
  message_id: string | null;
  client_message_id: string | null;
  role: "student";
  session_id: string;
  turn_id: string | null;
  content: ContentBlock[];
  ts: number | null;
  state: "sending" | "accepted" | "failed";
  /** Why a send failed: an error code of TABLE API-32a, shown with its copy key `error.<code>`. */
  error_code?: string;
  error_details?: Record<string, unknown>;
}

export interface ToolRec {
  call_id: string;
  name: string;
  render_class: "card" | "ephemeral";
  state: unknown;
}

export interface PartRec {
  part_id: string;
  turn_id: string | null;
  kind: string;
  index: number;
  status: "started" | "streaming" | "complete" | "error" | "interrupted" | "retracted";
  text: string;
  /** Markdown blocks that can no longer change (UIA-13); `tail` is the block still streaming. */
  settled_blocks: string[];
  tail: string;
  duration_ms?: number;
  tools?: Record<string, ToolRec>;
  visual_id?: string;
  card?: { request_id: string; card: Card; state: "open" | "answering" | "answered" | "cancelled"; answer_summary?: string; answered_ts?: number };
  notice?: Record<string, unknown>;
}

export interface RequestRec {
  request_id: string;
  part_id: string;
  card: Card;
  state: "open" | "answering" | "answered" | "cancelled";
  answer_summary?: string;
}

export interface StepRec {
  step_id: string;
  index: number;
  latex: string;
  reason: string | null;
  owner: "tutor" | "student";
  status: string;
  check_id: string | null;
  error: StepError | null;
}

export interface BoardRec {
  board_id: string;
  part_id: string | null;
  problem: { text: string; latex: string | null } | null;
  step_ids: string[];
  steps: Record<string, StepRec>;
  knowns: unknown[];
  unknowns: unknown[];
  conventions: unknown[];
  await: { step_id: string; prompt: string; input_kind: string } | null;
  highlight: { step_ids: string[]; ttl_ms: number | null; ts: number } | null;
  /** The line the board is on (the newest, or the one the student moved to): bound visuals follow it (VSL-20). */
  current: string | null;
}

export interface VisualRec {
  visual_id: string;
  part_id: string;
  spec: VisualsVisualSpecResolved;
  step: number;
  focus: { part_ids: string[]; ttl_ms: number | null; ts: number } | null;
}

/** A note the tutor saved because the student asked (MEM-11), announced in the conversation with an Undo until
 * `undo_until_ts` (server time). The snapshot does not carry these (G94): after a reload the note stays on the "What
 * your tutor knows" page, where it can still be forgotten. */
export interface MemoryRec {
  note_id: string;
  session_id: string;
  /** The turn the save belongs to, or null for a save announced between turns. */
  turn_id: string | null;
  text: string;
  undo_until_ts: number;
  state: "saved" | "forgotten";
  /** Stream order, so announcements outside a turn keep their order. */
  seq: number;
}

export interface Cursor {
  epoch: string;
  seq: number;
}

export interface Store {
  connection: Record<string, ConnectionSlice>;
  sessions: Record<string, SessionRec>;
  turns: Record<string, TurnRec>;
  messages: Record<string, MessageRec>;
  parts: Record<string, PartRec>;
  requests: Record<string, RequestRec>;
  boards: Record<string, BoardRec>;
  visuals: Record<string, VisualRec>;
  memory: Record<string, MemoryRec>;
  cursors: Record<string, Cursor>;
}

export function emptyStore(): Store {
  return { connection: {}, sessions: {}, turns: {}, messages: {}, parts: {}, requests: {}, boards: {}, visuals: {}, memory: {}, cursors: {} };
}

export function connectionKey(sessionId: string | null): string {
  return sessionId === null ? "app" : `session:${sessionId}`;
}

export function emptyConnection(): ConnectionSlice {
  return { state: "connecting", epoch: null, last_seq: 0, retry_at: null, lagging: false, resync: false, clock_offset_ms: 0, banner: false, last_event_ts: null };
}

/** Elapsed time of a turn's current phase in server time (UIA-22): the clock never jumps after a reconnect. */
export function elapsedMs(phaseStartedTs: number, connection: ConnectionSlice | undefined, now: number = Date.now()): number {
  return Math.max(0, now + (connection?.clock_offset_ms ?? 0) - phaseStartedTs);
}

/** How long the Undo of a saved note is still offered, in server time (MEM-11); 0 once the window has closed. */
export function undoLeftMs(memory: MemoryRec, connection: ConnectionSlice | undefined, now: number = Date.now()): number {
  if (memory.state !== "saved") return 0;
  return Math.max(0, memory.undo_until_ts - (now + (connection?.clock_offset_ms ?? 0)));
}

/** Time since the last event in server time, or null before any event. */
export function silenceMs(connection: ConnectionSlice | undefined, now: number = Date.now()): number | null {
  if (connection?.last_event_ts == null) return null;
  return Math.max(0, now + connection.clock_offset_ms - connection.last_event_ts);
}
