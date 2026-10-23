// Rendering UI components against a store fed with envelopes, as the session controller feeds it.
import { act, render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { StoreHolder, connectionKey, emptyConnection, hydrate, emptyStore, optimistic, reduce, type CoreSnapshot, type Envelope } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider, type Registry } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { defaultRegistry } from "../src/transcript/parts.js";

export const SESSION = `ses_${"0".repeat(26)}`;
export const EPOCH = "ep_ui_tests";
let seq = 0;
let ids = 0;

export function id(prefix: string): string {
  ids += 1;
  return `${prefix}_${ids.toString(32).toUpperCase().padStart(26, "0")}`;
}

export function snapshot(): CoreSnapshot {
  return {
    session: { session_id: SESSION, title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false },
    cursor: { epoch: EPOCH, seq: 0 },
    messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null,
  };
}

export class Fixture {
  readonly holder = new StoreHolder();
  turnId: string | null = null;

  constructor() {
    seq = 0;
    this.holder.update(() => hydrate(emptyStore(), snapshot()));
  }

  emit(event: Record<string, unknown> & { type: string }, turnId: string | null = this.turnId): Envelope {
    seq += 1;
    const envelope: Envelope = { v: 1, channel: "session", seq, epoch: EPOCH, session_id: SESSION, turn_id: turnId, ts: Date.now(), event };
    act(() =>
      this.holder.update((s) => {
        const next = reduce(s, envelope);
        const key = connectionKey(SESSION);
        // As the session controller does on each commit: server clock offset and the time of the last event.
        return { ...next, connection: { ...next.connection, [key]: { ...(next.connection[key] ?? emptyConnection()), state: "live", clock_offset_ms: envelope.ts - Date.now(), last_event_ts: envelope.ts } } };
      }),
    );
    return envelope;
  }

  send(text: string): string {
    const cli = id("cli");
    act(() => this.holder.update((s) => optimistic(s, SESSION, cli, [{ type: "text", text }])));
    return cli;
  }

  startTurn(cli: string | null = null): string {
    const turnId = id("trn");
    this.turnId = turnId;
    const msg = id("msg");
    this.emit({ type: "turn.start", turn_id: turnId, user_message_id: msg, client_message_id: cli, intent: "ask", mode: "guided", fork: false });
    if (cli !== null) this.emit({ type: "message.accepted", client_message_id: cli, message_id: msg, turn_id: turnId, disposition: "turn" });
    return turnId;
  }

  text(content: string, end = true): string {
    const partId = id("prt");
    this.emit({ type: "part.start", part_id: partId, kind: "text", index: 0 });
    this.emit({ type: "text.delta", part_id: partId, delta: content });
    if (end) this.emit({ type: "part.end", part_id: partId, status: "complete", duration_ms: 1 });
    return partId;
  }

  tool(name: string, status: "running" | "completed" | "error" = "completed"): string {
    const partId = id("prt");
    const callId = id("call");
    this.emit({ type: "part.start", part_id: partId, kind: "tool", index: 0 });
    const state = status === "error" ? { status, title: { pre: "x" }, code: "worker_error", message: "", retryable: false } : { status, title: { pre: "x" } };
    this.emit({ type: "tool.state", part_id: partId, call_id: callId, name, render_class: "ephemeral", state });
    if (status !== "running") this.emit({ type: "part.end", part_id: partId, status: status === "error" ? "error" : "complete", duration_ms: 1 });
    return partId;
  }

  status(phase: string, startedTs = Date.now(), tier: "fast" | "strong" = "fast"): void {
    this.emit({ type: "status", phase, label_key: null, progress: null, phase_started_ts: startedTs, model_tier: tier });
  }

  end(status = "complete", elapsedMs = 2000): void {
    this.emit({ type: "turn.end", status, stop_reason: status === "interrupted" ? "student_stop" : "completed", elapsed_ms: elapsedMs, usage: null, verification: "not_applicable", persisted: { message_id: id("msg"), part_ids: [] }, degraded: false, degraded_reason: null });
  }

  render(node: ReactNode, registry: Registry = defaultRegistry()): RenderResult {
    return render(
      <LocaleProvider locale="en">
        <RegistryProvider registry={registry}>
          <StoreProvider holder={this.holder} session={null}>
            {node}
          </StoreProvider>
        </RegistryProvider>
      </LocaleProvider>,
    );
  }
}
