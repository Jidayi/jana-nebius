// A fake local core for the stream client tests: it serves a recorded session (evals/recordings) over a fetch
// handler, frame by frame on a timer, and can be killed and restarted. A restart mints a new epoch and launch token,
// as the real core does, and resumes from the same point (its persisted state); old cursors then get 409.
import type { CoreSnapshot } from "../src/hydrate.js";
import type { Recording } from "./recordings.js";

export class FakeCore {
  epoch = "ep_fake_0";
  token = "token-0";
  position = 0; // frames emitted so far (in the recording)
  seqBase = 0; // the recording's seq at the current epoch's seq 0
  down = false;
  restarts = 0;
  turnKeys = new Map<string, number>();
  turnStarts = 0;
  private streams = new Set<ReadableStreamDefaultController<Uint8Array>>();
  private timer: ReturnType<typeof setInterval> | null = null;
  readonly encoder = new TextEncoder();
  serverOffsetMs = 0;

  constructor(readonly recording: Recording, readonly frameEveryMs = 2) {}

  start(): void {
    this.timer = setInterval(() => this.tick(), this.frameEveryMs);
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    for (const s of this.streams) s.error(new Error("stopped"));
    this.streams.clear();
  }

  get done(): boolean {
    return this.position >= this.recording.frames.length;
  }

  kill(): void {
    this.down = true;
    for (const s of this.streams) {
      try {
        s.error(new Error("core killed"));
      } catch {
        /* already closed */
      }
    }
    this.streams.clear();
  }

  restart(): void {
    this.restarts += 1;
    this.epoch = `ep_fake_${this.restarts}`;
    this.token = `token-${this.restarts}`;
    this.seqBase = this.position;
    this.down = false;
  }

  private frame(i: number): string {
    const recorded = this.recording.frames[i]!;
    const envelope = { ...recorded, epoch: this.epoch, seq: i + 1 - this.seqBase, ts: Date.now() + this.serverOffsetMs };
    return `id: ${envelope.epoch}:${envelope.seq}\nevent: ${envelope.event.type}\ndata: ${JSON.stringify(envelope)}\n\n`;
  }

  private tick(): void {
    if (this.down || this.done) return;
    const data = this.encoder.encode(this.frame(this.position));
    this.position += 1;
    for (const s of this.streams) s.enqueue(data);
  }

  snapshot(): CoreSnapshot {
    const snap = structuredClone(this.recording.snapshots[this.position]!);
    snap.cursor = { epoch: this.epoch, seq: this.position - this.seqBase };
    return snap;
  }

  fetch = async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    if (this.down) throw new TypeError("fetch failed: connection refused");
    const url = new URL(String(input));
    const headers = new Headers(init?.headers);
    if (headers.get("authorization") !== `Bearer ${this.token}`) {
      return json(401, { error: { code: "unauthorized", message: "", retryable: false, action_taken: false, request_id: "req_x" } });
    }
    const method = init?.method ?? "GET";
    if (method === "GET" && url.pathname.endsWith("/snapshot")) return json(200, this.snapshot());
    if (method === "GET" && url.pathname.endsWith("/events")) return this.events(headers.get("last-event-id"), init?.signal ?? null);
    if (method === "POST" && url.pathname.endsWith("/turns")) {
      const key = headers.get("idempotency-key") ?? "";
      if (!this.turnKeys.has(key)) {
        this.turnStarts += 1;
        this.turnKeys.set(key, this.turnStarts);
      }
      return json(202, { turn_id: `trn_${String(this.turnKeys.get(key)).padStart(26, "0")}`, message_id: `msg_${"0".repeat(26)}` });
    }
    return json(404, { error: { code: "not_found", message: "", retryable: false, action_taken: false, request_id: "req_x" } });
  };

  private events(cursor: string | null, signal: AbortSignal | null): Response {
    const [epoch, seqText] = (cursor ?? `${this.epoch}:0`).split(/:(?=[^:]*$)/);
    if (epoch !== this.epoch) return json(409, { error: { code: "epoch_mismatch", message: "", retryable: false, action_taken: false, request_id: "req_x" } });
    const from = Number(seqText) + this.seqBase;
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start: (c) => {
        controller = c;
        const replay = this.position - from;
        c.enqueue(this.encoder.encode(`event: control\ndata: ${JSON.stringify({ type: "stream.hello", protocol: { major: 1, minor: 0 }, server_version: "0", epoch: this.epoch, channel: "session", session_id: this.recording.session_id, resumed_from: Number(seqText), replayed: Math.max(0, replay) })}\n\n`));
        for (let i = from; i < this.position; i += 1) c.enqueue(this.encoder.encode(this.frame(i)));
        this.streams.add(c);
      },
      cancel: () => {
        this.streams.delete(controller);
      },
    });
    signal?.addEventListener("abort", () => {
      this.streams.delete(controller);
      try {
        controller.error(new Error("aborted"));
      } catch {
        /* closed */
      }
    });
    return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
  }
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
