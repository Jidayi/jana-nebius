/** Development-only browser replay; measurements are observations of this browser, never device-lab signoff. */
import { performanceFailures, type PerformanceSample } from "./performance-budget.js";
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { DeltaQueue, StoreHolder, emptyStore, hydrate, optimistic, reduce, type CoreSnapshot, type Envelope } from "@jana/client-core";
import { Board, Composer, LocaleProvider, RegistryProvider, StoreProvider, Transcript, defaultRegistry } from "@jana/ui";
const registry = defaultRegistry();
const SESSION = `ses_${"0".repeat(26)}`, BOARD = `brd_${"0".repeat(26)}`;
function fixture() {
  const holder = new StoreHolder(); let seq = 0, turn = "", part = "";
  const id = (prefix: string, n: number) => `${prefix}_${n.toString(32).toUpperCase().padStart(26, "0")}`;
  const snapshot: CoreSnapshot = { session: { session_id: SESSION, title: "Synthetic 500-turn performance replay", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false },
    cursor: { epoch: "0123456789abcdef", seq: 0 }, messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null };
  holder.update(() => hydrate(emptyStore(), snapshot));
  const envelope = (event: Envelope["event"]): Envelope => ({ v: 1, channel: "session", session_id: SESSION, turn_id: turn, epoch: "0123456789abcdef", seq: ++seq, ts: Date.now(), event });
  const emit = (event: Envelope["event"]) => holder.update((store) => reduce(store, envelope(event)));
  for (let n = 0; n < 500; n++) {
    turn = id("trn", n); part = id("prt", n); const cli = id("cli", n), msg = id("msg", n);
    holder.update((s) => optimistic(s, SESSION, cli, [{ type: "text", text: `Synthetic student question ${n}.` }]));
    emit({ type: "turn.start", turn_id: turn, user_message_id: msg, client_message_id: cli, intent: "ask", mode: "guided", fork: false });
    emit({ type: "message.accepted", client_message_id: cli, message_id: msg, turn_id: turn, disposition: "turn" });
    emit({ type: "part.start", part_id: part, kind: "text", index: 0 });
    emit({ type: "text.delta", part_id: part, delta: `Synthetic explanation ${n}.\n\nA settled paragraph with \\(v = u + at\\).\n\n` });
    if (n < 499) { emit({ type: "part.end", part_id: part, status: "complete", duration_ms: 1 }); emit({ type: "turn.end", status: "complete", stop_reason: "completed", elapsed_ms: 1, usage: null, verification: "not_applicable", persisted: { message_id: id("msg", n + 1000), part_ids: [part] }, degraded: false, degraded_reason: null }); }
  }
  for (let n = 0; n < 30; n++) emit({ type: "board.step", board_id: BOARD, step_id: id("stp", n), index: n, latex: `x_{${n}} = ${n}`, reason: "Synthetic checked step", owner: "tutor", status: "final", check_id: null, error: null });
  return { holder, delta: () => envelope({ type: "text.delta", part_id: part, delta: "word " }) };
}
const quantile = (values: number[], p: number) => { const sorted = [...values].sort((a, b) => a - b); return sorted.length === 0 ? null : Number((sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))] ?? 0).toFixed(2)); };
// Mutation self-test: reproduce a blocking board render without changing shipping BoardStep code.
function SlowBoard({ holder }: { holder: StoreHolder }) {
  const revision = useSyncExternalStore((fn) => holder.subscribe(fn), holder.getState);
  useLayoutEffect(() => {
    const end = performance.now() + 80;
    while (performance.now() < end) { /* deliberate regression */ }
  }, [revision]);
  return <Board sessionId={SESSION} />;
}
export function TranscriptBenchmark() {
  const [data, setData] = useState(fixture); const [running, setRunning] = useState(false), [report, setReport] = useState<unknown>(null);
  const root = useRef<HTMLDivElement>(null), stop = useRef<(() => void) | null>(null), paints = useRef<number[]>([]);
  useEffect(() => () => stop.current?.(), []);
  const run = () => {
    setReport(null); setRunning(true); paints.current = [];
    const frames: number[] = [], longTasks: number[] = []; const taskTimeline: { after_start_ms: number; duration_ms: number }[] = []; const started = performance.now(); let maxNodes = 0, maxDomNodes = 0, sent = 0, previous = 0, frame = 0;
    const longTasksSupported = PerformanceObserver.supportedEntryTypes.includes("longtask");
    const observer = longTasksSupported ? new PerformanceObserver((entries) => { for (const e of entries.getEntries()) { longTasks.push(e.duration); taskTimeline.push({ after_start_ms: Math.round(e.startTime - started), duration_ms: e.duration }); } }) : null;
    observer?.observe({ entryTypes: ["longtask"] });
    const queue = new DeltaQueue((batch) => data.holder.update((store) => batch.reduce(reduce, store)));
    const finish = () => { clearInterval(timer); cancelAnimationFrame(frame); queue.flush(); observer?.disconnect(); setRunning(false); const measured = { qualification: "Synthetic browser replay; hardware qualification is recorded separately by the runner", input_metric: "keydown-to-second-animation-frame upper bound (includes one paint opportunity)", turns: 500, board_steps: 30, deltas: sent, max_transcript_nodes: maxNodes, max_dom_nodes: maxDomNodes, frame_p50_ms: quantile(frames, .5), frame_p95_ms: quantile(frames, .95), input_p50_ms: quantile(paints.current, .5), input_p95_ms: quantile(paints.current, .95), input_samples: paints.current.length, long_tasks_supported: longTasksSupported, max_long_task_ms: longTasksSupported ? Math.max(0, ...longTasks) : null, task_timeline: taskTimeline }; setReport({ ...measured, budget_failures: performanceFailures(measured satisfies PerformanceSample) }); stop.current = null; };
    const sample = (now: number) => {
      if (previous !== 0) frames.push(now - previous); previous = now;
      const log = root.current?.querySelector<HTMLElement>('[role="log"]');
      if (log !== null && log !== undefined) {
        maxNodes = Math.max(maxNodes, log.querySelectorAll("*").length);
        maxDomNodes = Math.max(maxDomNodes, root.current?.querySelectorAll("*").length ?? 0);
        // Scroll at 1,200 px/s, independent of transcript length. Scaling speed by the full scrollHeight teleports
        // thousands of pixels each frame as history grows and measures repeated cold mounts instead of scrolling.
        const range = Math.max(1, log.scrollHeight - log.clientHeight), distance = (now - started) * 1.2 % (range * 2);
        log.scrollTop = distance <= range ? distance : range * 2 - distance;
      }
      frame = requestAnimationFrame(sample);
    };
    const timer = setInterval(() => { for (let i = 0; i < 50 && sent < 5000; i++, sent++) queue.push(data.delta()); if (sent === 5000) finish(); }, 200);
    frame = requestAnimationFrame(sample); stop.current = finish;
  };
  return <LocaleProvider locale="en"><RegistryProvider registry={registry}><StoreProvider holder={data.holder} session={null}>
    <div ref={root} className="flex h-screen flex-col" onKeyDownCapture={(event) => { if (!running || !(event.target instanceof HTMLElement) || event.target.closest('[contenteditable="true"], input, textarea') === null) return; const now = performance.now(); const start = event.timeStamp > 0 && event.timeStamp <= now ? event.timeStamp : now; requestAnimationFrame(() => requestAnimationFrame(() => paints.current.push(performance.now() - start))); }}>
      <div className="flex flex-wrap items-center gap-3 border-b border-line p-3"><h1>Transcript browser benchmark</h1><button disabled={running} onClick={run}>Replay 5,000 deltas</button><button disabled={running} onClick={() => { setData(fixture()); setReport(null); }}>Reset synthetic session</button><span role="status">{running ? "Replaying for about 20 seconds; type in the Ask box." : "Ready"}</span></div>
      {report !== null && <pre data-performance-report className="max-h-64 overflow-auto p-3">{JSON.stringify(report, null, 2)}</pre>}
      <div className="flex min-h-0 flex-1"><div className="flex min-h-0 flex-1 flex-col"><Transcript sessionId={SESSION} /><Composer sessionId={SESSION} hold={() => undefined} /></div><div className="w-64 overflow-auto">{new URLSearchParams(location.search).has("slow-board") ? <SlowBoard holder={data.holder} /> : <Board sessionId={SESSION} />}</div></div>
    </div>
  </StoreProvider></RegistryProvider></LocaleProvider>;
}
