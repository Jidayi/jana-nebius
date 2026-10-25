// The visual viewer (UIA-20, VSL-10, VSL-11, VSL-20, VSL-21, LOC-15, LOC-16): hosts a registry visual renderer with
// step controls (Previous, Next, "Step n of m"), the label mode switch, "Hide labels and quiz me" where the kind
// allows it, the tap-a-part info panel, the alt-text disclosure and, for graphs and charts, "Show as table". It
// re-validates each resolved spec on the client and shows the words fallback when it fails (VSL-16), so a bad spec
// never throws. Step changes from the board, from `visual.step` and from the student all go through `moveVisual`, so
// the visual and the board stay in step. The visual renders when it scrolls into view; simulations pause off screen.
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ComponentType, type ReactElement, type ReactNode } from "react";
import { CLIENT_KEYS, moveVisual, type VisualRec } from "@jana/client-core";
import { errors } from "@jana/contracts-ts/client";
import { useT } from "../i18n.js";
import { Button, Disclosure, FIELD_LOOK } from "../primitives/index.js";
import { useSelect, useStoreHolder } from "../store.js";
import { useVoicePointer } from "../voice/SpeechTools.js";

export type LabelMode = "shown" | "hidden" | "quiz";

export interface VisualSpec {
  type: string;
  visual_id: string;
  params: unknown;
  steps?: unknown[];
  labels?: LabelMode;
  parts?: { id: string; name: string; focusable: boolean }[];
  alt: { summary: string; steps: string[]; locale: string };
  computed?: Record<string, unknown>;
  status?: string;
}

/** What the viewer needs from a vetted renderer, given to it by the app (the UI never imports renderers, ARC-18). */
export interface VisualHooks {
  check(params: unknown): string[];
  labelModes: readonly LabelMode[];
  table?(spec: VisualSpec): { columns: string[]; rows: string[][] };
  View: ComponentType<{
    spec: VisualSpec; step: number; labels: LabelMode; focus: string[]; spotlight?: boolean; reducedMotion: boolean; textScale: number; visible: boolean;
    t: (key: string, args?: Record<string, string | number>) => string; onPartActivate(id: string): void;
    onSimEvent(event: { type: string; [k: string]: unknown }): void;
  }>;
  Fallback: ComponentType<{ spec: unknown; reason: string }>;
}

/** Display settings for visuals: reduced motion and text size (DSN-07, DSN-09), from the app or the gallery state. */
export interface VisualSettings {
  reducedMotion: boolean;
  /** Low-power mode (DSN-27, UXS-56): decorative motion such as the tutor's pen is hidden. */
  lowPower?: boolean;
  textScale: number;
  onSimEvent?(event: { type: string; [k: string]: unknown }): void;
  onAsk?(visualId: string, partId: string): void;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const SettingsContext = createContext<VisualSettings | null>(null);

export function VisualSettingsProvider({ settings, children }: { settings: VisualSettings; children: ReactNode }) {
  return <SettingsContext.Provider value={settings}>{children}</SettingsContext.Provider>;
}

export function useVisualSettings(): VisualSettings {
  return useContext(SettingsContext) ?? { reducedMotion: prefersReducedMotion(), textScale: 1 };
}

const NO_VISUAL = null;
const NO_PARTS: string[] = [];

/** Client re-validation (UIA-20): the resolved envelope, then the kind's params. */
export function revalidate(spec: unknown, hooks: VisualHooks): string[] {
  const envelope = errors("visuals/visual-spec#/$defs/resolved", spec);
  if (envelope.length > 0) return envelope;
  return hooks.check((spec as VisualSpec).params);
}

/** Whether the element is in the viewport: measured once before paint, then kept up to date by an observer. */
function useOnScreen(ref: { current: HTMLElement | null }): boolean {
  const [visible, setVisible] = useState(typeof IntersectionObserver === "undefined");
  useLayoutEffect(() => {
    const el = ref.current;
    if (el === null || typeof window === "undefined") return;
    const box = el.getBoundingClientRect();
    if (box.top < window.innerHeight && box.bottom >= 0) setVisible(true);
  }, [ref]);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined" || ref.current === null) return undefined;
    const observer = new IntersectionObserver((entries) => setVisible(entries.some((e) => e.isIntersecting)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [ref]);
  return visible;
}

export function VisualViewer({ spec, hooks }: { spec: VisualSpec; hooks: VisualHooks }): ReactElement {
  const t = useT();
  const settings = useVisualSettings();
  const holder = useStoreHolder();
  const record = useSelect((s) => s.visuals[spec.visual_id] ?? NO_VISUAL) as VisualRec | null;
  const box = useRef<HTMLDivElement>(null);
  const seen = useOnScreen(box);
  const [shownOnce, setShownOnce] = useState(false);
  const [localStep, setLocalStep] = useState(0);
  const [labels, setLabels] = useState<LabelMode>(spec.labels ?? "shown");
  const [part, setPart] = useState<string | null>(null);
  const [describe, setDescribe] = useState(false);
  const [table, setTable] = useState(false);
  const [focusNow, setFocusNow] = useState(() => Date.now());
  useEffect(() => {
    if (seen) setShownOnce(true);
  }, [seen]);

  const problems = revalidate(spec, hooks);
  const focusRec = record?.focus ?? null;
  const ttl = focusRec?.ttl_ms ?? CLIENT_KEYS.visual_focus_ttl_ms;
  const told = focusRec !== null && focusNow - focusRec.ts < ttl ? focusRec.part_ids : NO_PARTS;
  // A spoken cue on one of this visual's parts (VOC-10, VOC-51): the same pointer ring as `visual.focus`, fired by heard
  // playback and cleared with its cue (UXS-63). A part this visual does not have is never drawn (VSL-45).
  const pointer = useVoicePointer();
  const cued = pointer?.target.kind === "part" && pointer.target.visual_id === spec.visual_id
    && (spec.parts ?? []).some((p) => p.id === (pointer.target as { part_id: string }).part_id) ? (pointer.target as { part_id: string }).part_id : null;
  const focus = cued === null || told.includes(cued) ? told : [...told, cued];
  useEffect(() => {
    if (focusRec === null) return undefined;
    // The tutor's pointing clears after its time to live (VSL-21): one declared timer, not an animation loop.
    const left = Math.max(0, focusRec.ts + ttl - Date.now());
    const timer = setTimeout(() => setFocusNow(Date.now()), left + 1);
    setFocusNow(Date.now());
    return () => clearTimeout(timer);
  }, [focusRec, ttl]);

  if (problems.length > 0 || spec.status === "text_only") {
    return <div data-visual-viewer="fallback"><hooks.Fallback spec={spec} reason={problems.length > 0 ? "invalid" : "text_only"} /></div>;
  }
  const steps = spec.steps ?? [];
  const step = record !== null ? record.step : localStep;
  const go = (n: number) => {
    if (record !== null) holder.update((s) => moveVisual(s, spec.visual_id, n, "student"));
    else setLocalStep(Math.max(0, Math.min(steps.length - 1, n)));
  };
  const names = new Map((spec.parts ?? []).map((p) => [p.id, p.name]));
  const entryParts = ((spec.computed?.entry as { parts?: { id: string; name: string; function?: string }[] } | undefined)?.parts ?? []);
  const info = part === null ? null : { name: names.get(part) ?? part, fn: entryParts.find((p) => p.id === part)?.function ?? null };
  const tableData = table && hooks.table !== undefined ? hooks.table(spec) : null;
  const modes = hooks.labelModes;
  const focusableParts = (spec.parts ?? []).filter((p) => p.focusable);
  const partLabel = (id: string) => labels === "shown" ? names.get(id) ?? id : t(labels === "quiz" ? "visual.part.blank" : "visual.part.hidden", { index: focusableParts.findIndex((p) => p.id === id) + 1, count: focusableParts.length });
  return (
    <section ref={box} className="my-2 rounded-card border border-line bg-canvas p-3" data-visual-viewer={spec.type}>
      {shownOnce || seen ? (
        tableData === null ? (
          <hooks.View spec={spec} step={step} labels={labels} focus={focus} spotlight={focusRec?.spotlight === true && told.length > 0} reducedMotion={settings.reducedMotion} textScale={settings.textScale}
            visible={seen} t={t} onPartActivate={(id) => setPart(id)} onSimEvent={(e) => settings.onSimEvent?.(e)} />
        ) : (
          <table className="w-full text-ui" data-visual-table="true">
            <thead><tr>{tableData.columns.map((c) => <th key={c} scope="col" className="text-start">{t(c)}</th>)}</tr></thead>
            <tbody>{tableData.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j} className="tabular-nums">{cell}</td>)}</tr>)}</tbody>
          </table>
        )
      ) : (
        <p className="text-ui text-muted">{spec.alt.summary}</p>
      )}
      {focus.length > 0 && <p className="sr-only" aria-live="polite">{t("visual.viewer.showing", { parts: focus.map(partLabel).join(", ") })}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {focusableParts.length > 0 && <label className="flex flex-col gap-1 text-meta text-muted">{t("visual.viewer.choose_part")}
          <select className={FIELD_LOOK} data-part-equivalents={JSON.stringify(focusableParts.map((p) => p.id))} value={part ?? ""} onChange={(e) => setPart(e.target.value || null)}>
            <option value="">{t("visual.viewer.choose_part")}</option>
            {focusableParts.map((p) => <option key={p.id} value={p.id}>{partLabel(p.id)}</option>)}
          </select>
        </label>}
        {steps.length > 0 && (
          <>
            <Button onClick={() => go(step - 1)} disabled={step <= 0}>{t("visual.viewer.previous")}</Button>
            <span className="text-meta text-muted tabular-nums" aria-live="polite" data-visual-step={step}>{t("visual.viewer.step", { n: Math.max(step, 0) + 1, m: steps.length })}</span>
            <Button onClick={() => go(step + 1)} disabled={step >= steps.length - 1}>{t("visual.viewer.next")}</Button>
          </>
        )}
        {modes.includes("hidden") && (
          <Button onClick={() => setLabels(labels === "shown" ? "hidden" : "shown")} aria-pressed={labels !== "shown"}>{t(labels === "shown" ? "visual.viewer.labels_hidden" : "visual.viewer.labels_shown")}</Button>
        )}
        {modes.includes("quiz") && labels !== "quiz" && <Button onClick={() => setLabels("quiz")}>{t("visual.viewer.quiz")}</Button>}
        {hooks.table !== undefined && (
          <Button onClick={() => setTable(!table)} aria-pressed={table}>{t(table ? "visual.viewer.hide_table" : "visual.viewer.show_table")}</Button>
        )}
      </div>
      {info !== null && (
        <div className="mt-2 rounded-card border border-line p-2" role="region" aria-label={partLabel(part ?? "")} data-visual-part-panel={part ?? ""}>
          <p className="text-ui font-medium">{partLabel(part ?? "")}</p>
          {labels === "shown" && info.fn !== null && <p className="text-ui text-muted">{info.fn}</p>}
          <div className="mt-1 flex gap-2">
            {settings.onAsk !== undefined && <Button onClick={() => settings.onAsk?.(spec.visual_id, part ?? "")}>{t("visual.viewer.part_ask")}</Button>}
            <Button onClick={() => setPart(null)}>{t("visual.viewer.part_close")}</Button>
          </div>
        </div>
      )}
      <div className="mt-2">
        <Disclosure summary={t("visual.viewer.describe")} open={describe} onToggle={() => setDescribe(!describe)}>
          <p className="text-ui" data-visual-alt="true">
            {labels === "shown" ? spec.alt.summary : t(labels === "quiz" ? "visual.alt.quiz" : "visual.alt.labels_hidden", { count: (spec.parts ?? []).filter((p) => p.focusable).length })}
            {labels === "shown" && step >= 0 && spec.alt.steps[step] !== undefined ? ` ${spec.alt.steps[step]}` : ""}
          </p>
        </Disclosure>
      </div>
    </section>
  );
}
