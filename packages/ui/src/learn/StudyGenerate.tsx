// The study area's Generate panel, its settings dialogs and My Sets (STU-21, D118), and a recording's player with its
// chapters and the transcript that follows playback (STU-22).
import { useEffect, useMemo, useRef, useState } from "react";
import { GENERATE_TOOLS, type GenerateTool, type StudyContracts as W } from "@jana/client-core";
import { useT } from "../i18n.js";
import { Icon, type IconName } from "../icons.js";
import { Button, Dialog, FIELD_LOOK, Notice, SegmentedControl, Switch } from "../primitives/index.js";

const TOOL_ICON: Record<GenerateTool, IconName> = { summary: "notes", quiz: "question", flashcards: "practice", notes: "learn", audio_overview: "read-aloud", lesson_plan: "timer" };
/** The question types a learner picks from (STU-21); a number and an expression are one choice. */
const QUESTION_TYPES = [["choice"], ["multi_select"], ["numeric", "expression"], ["fill_blank"], ["true_false"], ["free_response"]] as const;
type QuizType = W.QuizType;
export type GenerateRequest = { count: number; settings: W.GenerateSettings };

/** The six tools of a material, each opening its settings. Before any material, they show greyed with the reason. */
export function GenerateTools({ disabled, empty = false, onPick }: { disabled: boolean; empty?: boolean; onPick: (tool: GenerateTool) => void }) {
  const t = useT();
  return <section className="flex flex-col gap-3" aria-labelledby="study-generate">
    <h2 id="study-generate" className="text-ui font-semibold text-ink">{t("study.generate_heading")}</h2>
    {empty && <p className="text-meta text-muted">{t("study.generate_needs_material")}</p>}
    <div className="grid grid-cols-2 gap-2">
      {GENERATE_TOOLS.map((tool) => <button key={tool} type="button" disabled={disabled || empty} onClick={() => onPick(tool)}
        className="jana-press flex min-h-16 items-start gap-3 rounded-card border border-line bg-canvas px-3 py-3 text-start hover:bg-wash disabled:cursor-not-allowed disabled:bg-chrome disabled:text-faint">
        <span aria-hidden="true" className="mt-0.5 text-muted"><Icon name={TOOL_ICON[tool]} size={20} /></span>
        <span className="flex min-w-0 flex-col gap-0.5"><span className="text-ui font-medium">{t(`study.tool.${tool}`)}</span><span className="text-meta text-muted">{t(`study.tool_help.${tool}`)}</span></span>
      </button>)}
    </div>
  </section>;
}

/** One tool's settings (STU-21): what it takes, all topics kept by default, and Generate. */
export function GenerateDialog({ tool, topics, syllabi, busy, error = null, onClose, onGenerate }: {
  tool: GenerateTool | null; topics: W.MaterialTopics["items"]; syllabi: { source_id: string; revision: number; title: string }[];
  busy: boolean; error?: string | null; onClose: () => void; onGenerate: (tool: GenerateTool, request: GenerateRequest) => void;
}) {
  const t = useT();
  const [types, setTypes] = useState<QuizType[]>(["choice", "fill_blank", "true_false"]);
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium");
  const [count, setCount] = useState(10), [focus, setFocus] = useState("");
  const [kept, setKept] = useState<string[]>([]), [syllabus, setSyllabus] = useState<string[]>([]);
  const [length, setLength] = useState<"short" | "standard">("standard"), [voices, setVoices] = useState<"1" | "2">("1");
  const [minutes, setMinutes] = useState(45), [readyBy, setReadyBy] = useState("");
  useEffect(() => setKept(topics.map((topic) => topic.title)), [topics]);
  if (tool === null) return null;
  const takesTopics = tool !== "audio_overview";
  const quiz = tool === "quiz", cards = tool === "flashcards";
  const ready = (!quiz || types.length > 0) && (!takesTopics || topics.length === 0 || kept.length > 0);
  const toggle = (group: readonly QuizType[]) => setTypes((now) => group.every((x) => now.includes(x)) ? now.filter((x) => !group.includes(x)) : [...now, ...group.filter((x) => !now.includes(x))]);
  const build = (): GenerateRequest => {
    const settings: W.GenerateSettings = {};
    if (quiz) { settings.question_types = types; settings.difficulty = difficulty; }
    if (takesTopics && topics.length > 0) settings.topics = kept;
    if (takesTopics && focus.trim()) settings.focus = focus.trim();
    if (quiz && syllabus.length > 0) settings.syllabus = syllabi.filter((s) => syllabus.includes(s.source_id)).map(({ source_id, revision }) => ({ source_id, revision }));
    if (tool === "audio_overview") { settings.podcast_length = length; settings.voices = voices === "2" ? 2 : 1; }
    if (tool === "lesson_plan") { settings.minutes_available = minutes; if (readyBy) settings.ready_by = readyBy; }
    return { count, settings };
  };
  return <Dialog open heading={t(`study.tool.${tool}`)} closeLabel={t("action.cancel")} onClose={onClose} wide>
    <form className="flex flex-col gap-5" onSubmit={(e) => { e.preventDefault(); if (ready) onGenerate(tool, build()); }}>
      {quiz && <fieldset className="flex flex-col gap-2"><legend className="text-ui font-semibold">{t("study.setting.types")}</legend>
        <div className="grid grid-cols-2 gap-x-4">{QUESTION_TYPES.map((group) => <label key={group[0]} className="flex min-h-11 items-center gap-2 text-ui"><input type="checkbox" checked={group.every((x) => types.includes(x))} onChange={() => toggle(group)} />{t(`study.qtype.${group[0]}`)}</label>)}</div>
      </fieldset>}
      {quiz && <div className="flex flex-col gap-2"><span className="text-ui font-semibold">{t("study.setting.difficulty")}</span><SegmentedControl label={t("study.setting.difficulty")} value={difficulty} onChange={setDifficulty} options={(["easy", "medium", "hard"] as const).map((v) => ({ value: v, label: t(`study.difficulty.${v}`) }))} /></div>}
      {(quiz || cards) && <label className="flex items-center gap-3 text-ui text-ink">{t(quiz ? "study.count_questions" : "study.count_cards")}<span className="w-20 shrink-0"><input type="number" min={1} max={40} value={count} className={FIELD_LOOK} onChange={(e) => setCount(Math.max(1, Math.min(40, Math.trunc(Number(e.target.value)) || 1)))} /></span></label>}
      {tool === "audio_overview" && <>
        <div className="flex flex-col gap-2"><span className="text-ui font-semibold">{t("study.setting.length")}</span><SegmentedControl label={t("study.setting.length")} value={length} onChange={setLength} options={[{ value: "short", label: t("study.length.short") }, { value: "standard", label: t("study.length.standard") }]} /></div>
        <div className="flex flex-col gap-2"><span className="text-ui font-semibold">{t("study.setting.voices")}</span><SegmentedControl label={t("study.setting.voices")} value={voices} onChange={setVoices} options={[{ value: "1", label: t("study.voices.one") }, { value: "2", label: t("study.voices.two") }]} /></div>
      </>}
      {tool === "lesson_plan" && <div className="flex flex-wrap gap-4">
        <label className="flex flex-col gap-2 text-ui text-ink">{t("study.setting.minutes")}<span className="w-28 shrink-0"><input type="number" min={10} max={600} step={5} value={minutes} className={FIELD_LOOK} onChange={(e) => setMinutes(Math.max(10, Math.min(600, Math.trunc(Number(e.target.value)) || 10)))} /></span></label>
        <label className="flex flex-col gap-2 text-ui text-ink">{t("study.setting.ready_by")}<span className="w-44 shrink-0"><input type="date" value={readyBy} className={FIELD_LOOK} onChange={(e) => setReadyBy(e.target.value)} /></span></label>
      </div>}
      {takesTopics && topics.length > 0 && <fieldset className="flex flex-col gap-2"><legend className="text-ui font-semibold">{t("study.setting.topics")}</legend>
        <p className="text-meta text-muted">{t("study.setting.topics_help")}</p>
        <div className="flex flex-wrap gap-2">{topics.map((topic) => { const on = kept.includes(topic.title); return <Button key={topic.title} size="sm" tone={on ? "secondary" : "ghost"} aria-pressed={on} onClick={() => setKept((now) => on ? now.filter((x) => x !== topic.title) : [...now, topic.title])}>{topic.title}</Button>; })}</div>
        {kept.length === 0 && <p role="status" className="text-meta text-muted">{t("study.setting.topics_none")}</p>}
      </fieldset>}
      {takesTopics && <label className="flex flex-col gap-2 text-ui text-ink">{t("study.setting.focus")}<textarea rows={2} maxLength={500} value={focus} placeholder={t("study.setting.focus_placeholder")} className={`${FIELD_LOOK} py-2`} onChange={(e) => setFocus(e.target.value)} /></label>}
      {quiz && syllabi.length > 0 && <fieldset className="flex flex-col gap-1"><legend className="text-ui font-semibold">{t("study.setting.syllabus")}</legend>
        <p className="text-meta text-muted">{t("study.setting.syllabus_help")}</p>
        {syllabi.map((s) => { const on = syllabus.includes(s.source_id); return <label key={s.source_id} className="flex min-h-11 items-center gap-2 text-ui"><input type="checkbox" checked={on} disabled={!on && syllabus.length >= 3} onChange={() => setSyllabus((now) => on ? now.filter((x) => x !== s.source_id) : [...now, s.source_id])} />{s.title}</label>; })}
      </fieldset>}
      {error && <Notice message={error} />}
      <div className="flex gap-2"><Button type="submit" tone="primary" disabled={busy || !ready}>{t("study.generate_action")}</Button><Button tone="ghost" onClick={onClose}>{t("action.cancel")}</Button></div>
    </form>
  </Dialog>;
}

/** A set's live progress in words (STU-21): questions left, or cards due today. */
export function progressText(t: ReturnType<typeof useT>, progress: W.SetProgress | undefined): string | null {
  if (!progress) return null;
  if ("questions_left" in progress) return progress.questions_left === 0 ? t("study.sets.quiz_done") : t("study.sets.questions_left", { count: progress.questions_left });
  return t("study.sets.cards_due", { count: progress.cards_due_today });
}

/** My Sets (STU-21): every generated aid with its progress; a private source's sets keep their title hidden. */
export function MySets({ sets, busy, onOpen, heading = true }: { sets: W.StudySet[]; busy: boolean; onOpen: (set: W.StudySet) => void; heading?: boolean }) {
  const t = useT();
  const [confirm, setConfirm] = useState<string | null>(null);
  if (sets.length === 0) return heading ? <section className="flex flex-col gap-2" aria-labelledby="study-sets"><h2 id="study-sets" className="px-1 text-label font-medium text-faint">{t("study.sets.title")}</h2><p className="px-1 text-meta text-muted">{t("study.sets.empty")}</p></section> : null;
  return <section className="flex flex-col gap-2" aria-labelledby={heading ? "study-sets" : undefined} aria-label={heading ? undefined : t("study.sets.title")}>
    {heading && <h2 id="study-sets" className="px-1 text-label font-medium text-faint">{t("study.sets.title")}</h2>}
    <ul className="flex flex-col">{sets.map((set) => { const progress = progressText(t, set.progress); return <li key={set.aid_id} className="flex flex-col gap-2 py-1">
      <div className="flex items-center gap-3">
        <Button tone="ghost" disabled={busy} onClick={() => { if (set.private && !set.title) setConfirm(set.aid_id); else onOpen(set); }}>
          <Icon name={set.kind === "chapters" ? "table" : TOOL_ICON[set.kind as GenerateTool] ?? "notes"} size={16} />{t(`study.tool.${set.kind}`)} · {set.title ?? t("study.private_source")}
        </Button>
        <span className="flex-1" />
        {set.status === "stale" ? <p className="text-meta text-muted">{t("study.stale")}</p> : progress && <p className="text-meta text-muted">{progress}</p>}
      </div>
      {confirm === set.aid_id && <div className="flex flex-col items-start gap-2 px-4"><p className="text-ui">{t("study.private_confirm")}</p><div className="flex gap-2"><Button size="sm" onClick={() => { setConfirm(null); onOpen(set); }}>{t("study.open_private")}</Button><Button size="sm" tone="ghost" onClick={() => setConfirm(null)}>{t("action.cancel")}</Button></div></div>}
    </li>; })}</ul>
  </section>;
}

const clock = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

/** STU-22: an owned recording's player, its chapters and the transcript that follows playback. Selecting a chapter or
 * a line seeks the player; a citation elsewhere seeks through `playhead`. */
export function RecordingPlayer({ chunks, chapters, playhead, loadMedia, onSeek, onCite, canMakeChapters, onMakeChapters, busy }: {
  chunks: W.Chunk[]; chapters: W.Chapter[] | null; playhead: { ms: number; seq: number } | null; loadMedia: () => Promise<Blob | null>;
  onSeek: (ms: number) => void; onCite: (citation: W.Citation) => void; canMakeChapters: boolean; onMakeChapters: () => void; busy: boolean;
}) {
  const t = useT();
  const player = useRef<HTMLAudioElement>(null), transcript = useRef<HTMLOListElement>(null);
  const [url, setUrl] = useState<string | null>(null), [now, setNow] = useState(0), [follow, setFollow] = useState(true);
  const lines = useMemo(() => chunks.filter((c) => c.locator.kind === "time"), [chunks]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  const at = (ms: number) => { setNow(ms); if (player.current) player.current.currentTime = ms / 1000; };
  useEffect(() => { if (playhead) at(playhead.ms); }, [playhead?.seq]);
  const current = lines.findIndex((c) => c.locator.kind === "time" && c.locator.start_ms <= now && now < c.locator.end_ms);
  useEffect(() => {
    if (!follow || current < 0) return;
    transcript.current?.querySelector<HTMLElement>(`[data-line="${current}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [current, follow]);
  const seek = (ms: number) => { onSeek(ms); at(ms); };
  return <section className="flex flex-col gap-4" aria-label={t("study.recording.title")}>
    {url ? <audio ref={player} controls src={url} className="w-full" onTimeUpdate={(e) => setNow(Math.round(e.currentTarget.currentTime * 1000))} aria-label={t("study.recording.player")} />
      : <span><Button size="sm" disabled={busy} onClick={() => { void loadMedia().then((blob) => { if (blob) setUrl(URL.createObjectURL(blob)); }); }}><Icon name="read-aloud" size={16} />{t("study.recording.load")}</Button></span>}
    <section className="flex flex-col gap-2" aria-labelledby="study-chapters">
      <h2 id="study-chapters" className="text-ui font-semibold text-ink">{t("study.recording.chapters")}</h2>
      {chapters === null ? <div className="flex flex-col items-start gap-2"><p className="text-meta text-muted">{t("study.recording.no_chapters")}</p><Button size="sm" disabled={busy || !canMakeChapters} onClick={onMakeChapters}>{t("study.generate.chapters")}</Button></div>
        : <ol className="flex flex-col gap-3">{chapters.map((chapter, i) => { const active = chapter.start_ms <= now && now < chapter.end_ms; return <li key={chapter.start_ms} className="flex flex-col gap-1">
          <button type="button" aria-current={active || undefined} onClick={() => seek(chapter.start_ms)} className="jana-press flex min-h-9 w-full items-center rounded-control px-2 text-start text-ui font-medium text-ink hover:bg-wash aria-[current]:bg-wash">{clock(chapter.start_ms)} · {chapter.title}</button>
          {chapter.summary.map((claim, j) => <div key={j} className="flex flex-wrap items-baseline gap-2 ps-2"><p className="text-meta text-ink">{claim.text}</p>{claim.citations.map((c, k) => <Button key={k} size="sm" tone="ghost" onClick={() => onCite(c)}>{t("study.citation", { number: k + 1 })}</Button>)}</div>)}
          <span className="sr-only">{t("study.recording.chapter_number", { number: i + 1 })}</span>
        </li>; })}</ol>}
    </section>
    <section className="flex flex-col gap-2" aria-labelledby="study-transcript">
      <div className="flex items-center gap-3"><h2 id="study-transcript" className="text-ui font-semibold text-ink">{t("study.recording.transcript")}</h2><span className="flex-1" /><Switch label={t("study.recording.auto_scroll")} checked={follow} onChange={setFollow} /></div>
      <ol ref={transcript} className="flex max-h-96 flex-col gap-1 overflow-y-auto">{lines.map((line, i) => line.locator.kind === "time" && <li key={line.chunk_id} data-line={i}>
        <button type="button" aria-current={i === current || undefined} onClick={() => { if (line.locator.kind === "time") seek(line.locator.start_ms); }}
          className="flex w-full gap-3 rounded-control px-2 py-1 text-start hover:bg-wash aria-[current]:bg-highlight-soft">
          <span className="shrink-0 text-meta text-faint">{clock(line.locator.start_ms)}</span><span className="text-body text-ink">{line.text}</span>
        </button>
      </li>)}</ol>
    </section>
  </section>;
}
