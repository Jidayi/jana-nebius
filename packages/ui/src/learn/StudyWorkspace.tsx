// Study from your materials (STU, D61–D64): the library with My Sets, then an opened material as a split view, the
// material on the left (a recording with its player, chapters and transcript, STU-22) and its study tools on the
// right: the Generate panel with each tool's settings (STU-21, D118) and Chat, with the ask box docked at the foot of
// the tools so a question about the material is always one step away.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { followUps, type GenerateTool, type StudyContracts as W, type StudyWorkspaceController } from "@jana/client-core";
import { useT } from "../i18n.js";
import { Icon } from "../icons.js";
import { Button, EmptyState, ErrorState, FIELD_LOOK, IconButton, Loader, Notice } from "../primitives/index.js";
import { FollowUpChips, HelpChips } from "../chips/NextStepChips.js";
import { ComposerShell } from "../primitives/ComposerShell.js";
import { PackInline, PackText } from "./PackText.js";
import { useOpenLesson, useOpenTopic } from "./link.js";
import { GenerateDialog, GenerateTools, MySets, RecordingPlayer } from "./StudyGenerate.js";

const ACCEPT = ".pdf,.txt,.md,.docx,.odt,.pptx,.odp,.png,.jpg,.jpeg,.webp,.wav,.mp3,.m4a,.mp4,.webm,.ogg,.flac,.aac,.mov,.mkv,.avi";
export type StudyTab = "generate" | "chat";
type Tab = StudyTab;
const TABS: readonly Tab[] = ["generate", "chat"];
/** The tab an aid of this kind lives under: a chat reply under Chat, every generated aid under Generate. */
const tabOf = (kind: string): Tab => (kind === "chat" ? "chat" : "generate");
/** A multi-select answer is its chosen option ids, comma-separated (STU-21). */
const picked = (answer: string | undefined) => (answer ?? "").split(",").filter(Boolean);

/** `onTab` hears which tab is open: the voice conversation lives in Chat (VOC-53, D130). */
export function StudyWorkspace({ controller, onPractice, onTab }: { controller: StudyWorkspaceController; onPractice?: (subject: string, kcIds: string[]) => void; onTab?: (tab: Tab) => void }) {
  const openLesson = useOpenLesson(), openTopic = useOpenTopic();
  const view = useSyncExternalStore(controller.subscribe, controller.getView, controller.getView), t = useT();
  const [title, setTitle] = useState(""), [text, setText] = useState(""), [confirm, setConfirm] = useState<string | null>(null);
  const [pageImage, setPageImage] = useState<{ url: string; page: number } | null>(null);
  const pageUrl = useRef<string | null>(null);
  useEffect(() => {
    if (pageUrl.current) URL.revokeObjectURL(pageUrl.current);
    pageUrl.current = null; setPageImage(null);
    return () => { if (pageUrl.current) URL.revokeObjectURL(pageUrl.current); pageUrl.current = null; };
  }, [view.source?.source_id, view.source?.revision]);
  const showPage = (page: number, revision: number, sourceId: string) => { void controller.loadPage(page, revision, sourceId).then((blob) => {
    if (blob === null) return;
    if (pageUrl.current) URL.revokeObjectURL(pageUrl.current);
    const url = URL.createObjectURL(blob); pageUrl.current = url; setPageImage({ url, page });
  }); };
  // D133: study tools are made online (the online plan); reading a document stays on this computer.
  const preferCloud = true;
  const [chatPrompt, setChatPrompt] = useState(""), [noteConfirm, setNoteConfirm] = useState<string | null>(null), [extraConfirm, setExtraConfirm] = useState<string | null>(null);
  const [readableConfirmed, setReadableConfirmed] = useState(false);
  useEffect(() => setReadableConfirmed(false), [view.source?.source_id, view.source?.revision]);
  const [correcting, setCorrecting] = useState(false), [correctedText, setCorrectedText] = useState("");
  const [deleting, setDeleting] = useState(false), [revealed, setRevealed] = useState(false), [answers, setAnswers] = useState<Record<string, string>>({});
  const [citation, setCitation] = useState<W.Citation | null>(null), [tool, setTool] = useState<GenerateTool | null>(null);
  const [pasting, setPasting] = useState(false), [managing, setManaging] = useState(false), [dragging, setDragging] = useState(false);
  const [tab, setTab] = useState<Tab>(view.aid ? tabOf(view.aid.kind) : "generate");
  useEffect(() => { onTab?.(tab); }, [onTab, tab]);
  useEffect(() => { if (view.aid) setTab(tabOf(view.aid.kind)); }, [view.aid?.aid_id, view.aid?.kind]);
  const passage = useRef<HTMLDivElement>(null), returnFocus = useRef<HTMLElement | null>(null), ask = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { void controller.load(); return () => controller.close(); }, [controller]);
  const active = view.reading || view.cleanupPending || view.jobs.some((j) => ["running", "queued", "waiting_online"].includes(j.state));
  useEffect(() => {
    if (!active && !view.source?.private) return;
    const timer = setInterval(() => { void controller.refreshOpened(); }, 2000);
    return () => clearInterval(timer);
  }, [controller, active, view.source?.private]);
  const card = view.deck?.cards.find((c) => !c.suspended);
  useEffect(() => setRevealed(false), [card?.card_id]);
  // A quiz opens where it was left: its draft answers, scrolled to the question the learner was on (STU-21).
  const quizBox = useRef<HTMLFormElement>(null);
  // ASM-28: a first wrong answer never shows the answer; it offers help and a second attempt. The explanation shows
  // after the second attempt, or when the learner asks for it.
  const [round, setRound] = useState(0), [shownAnswers, setShownAnswers] = useState<string[]>([]);
  useEffect(() => { setRound(0); setShownAnswers([]); }, [view.quiz?.quiz_id]);
  useEffect(() => { if (view.result) setRound((r) => r + 1); }, [view.result?.attempt_id]);
  const help = (kind: string, stem: string) => { setChatPrompt(`${t(`help.ask.${kind}`)}\n${stem}`); ask.current?.focus(); };
  useEffect(() => {
    const draft = view.quiz?.draft;
    setAnswers(draft ? Object.fromEntries(draft.answers.map((a) => [a.item_id, a.answer])) : {});
    if (draft) quizBox.current?.querySelector<HTMLElement>(`[data-item="${draft.position}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [view.quiz?.quiz_id]);
  const answer = (id: string, value: string, position: number, save = true) => {
    const next = { ...answers, [id]: value };
    setAnswers(next);
    if (save) void controller.saveDraft(next, position);
  };
  useEffect(() => { setCitation(null); setDeleting(false); setCorrecting(false); }, [view.source?.source_id]);
  useEffect(() => { if (citation) passage.current?.focus(); }, [citation]);
  const cite = (c: W.Citation) => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void controller.readCitation(c).then((ok) => { if (ok) setCitation(c); });
  };
  const claim = (c: W.Claim, key?: string) => <div key={key} className="flex flex-col items-start gap-2">
    <PackText text={c.text} />
    <div className="flex flex-wrap gap-2">{c.citations.map((ref, i) => <Button key={`${ref.chunk_id}-${i}`} size="sm" tone="ghost" disabled={view.busy} onClick={() => cite(ref)}>{t("study.citation", { number: i + 1 })}{revisionTag(ref.revision)}</Button>)}</div>
  </div>;
  // A revision is worth naming only once the material has been replaced: "revision 1" on a first upload is noise.
  const revisionTag = (revision: number) => revision > 1 ? ` · ${t("study.revision", { revision })}` : "";
  const errorText = (code: string) => t(`study.error.${code}`) === `study.error.${code}` ? t("study.error.generic") : t(`study.error.${code}`);
  const ready = view.source?.state === "ready" || (view.source?.state === "partial" && readableConfirmed);

  const status = <>
    {view.cleanupPending && <Notice message={t("study.cleanup_pending")} />}
    {view.status === "loading" && <Loader label={t("study.loading")} />}
    {view.status === "failed" && <ErrorState message={t("study.load_failed")} action={{ label: t("action.try_again"), onClick: () => { void controller.load(); } }} />}
    {view.error && <Notice message={view.safetyTemplate ? t(`study.safety.${view.safetyTemplate}`) : errorText(view.error)} />}
    {view.error === "graded_work" && <span><Button onClick={() => { setChatPrompt(t("study.guided_help")); setTab("chat"); ask.current?.focus(); }}>{t("study.guided_help")}</Button></span>}
    {view.busy && <p role="status" className="text-ui text-muted">{view.uploadTotal > 0 && view.uploadBytes < view.uploadTotal ? t("study.uploading", { done: view.uploadBytes, total: view.uploadTotal }) : t("study.working")}</p>}
  </>;

  const jobs = (list: typeof view.jobs) => list.length > 0 && <section className="flex flex-col gap-2" aria-label={t("study.jobs")}>
    {list.map((job) => <div key={job.job_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control bg-chrome px-3 py-2">
      <p className="text-ui font-medium text-ink">{t(`study.generate.${job.kind}`)}</p>
      <p role="status" className="text-meta text-muted">{t(`study.job.${job.state}`)}{job.total_units !== null ? ` · ${job.completed_units}/${job.total_units}` : ""}</p>
      <span className="flex-1" />
      {job.error && <p className="w-full text-meta text-muted">{errorText(job.error)}</p>}
      {job.notice === "allowance_exhausted" && <Notice message={t("study.allowance_fallback")} />}
      {["queued", "running", "waiting_online", "paused"].includes(job.state) && <Button size="sm" tone="ghost" disabled={view.busy} onClick={() => { void controller.jobAction(job.job_id, "cancel"); }}>{t("action.cancel")}</Button>}
      {["failed", "paused", "waiting_online"].includes(job.state) && <Button size="sm" disabled={view.busy} onClick={() => { void controller.jobAction(job.job_id, job.state === "failed" ? "retry" : "resume"); }}>{t("action.try_again")}</Button>}
    </div>)}
  </section>;

  // --- the library -------------------------------------------------------------------------------------------------
  if (!view.source) return <section className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-10" aria-labelledby="study-heading">
    <header className="flex flex-col gap-2">
      <h1 id="study-heading" className="text-title text-ink">{t("study.title")}</h1>
      <p className="text-ui text-muted">{t("study.about")}</p>
    </header>
    {status}
    <div className="flex flex-col gap-4 rounded-card border border-line bg-canvas p-5">
      {/* A drop zone over the native picker, which stays in the tab order (focus rings the whole zone). */}
      <label data-study-drop={dragging ? "over" : ""} onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }} onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); const file = e.dataTransfer.files[0]; if (file && !view.busy) void controller.upload(file, undefined, false); }}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-card border border-dashed px-6 py-8 text-center has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-focus ${dragging ? "border-focus bg-panel" : "border-line-strong hover:bg-wash"}`}>
        <span aria-hidden="true" className="flex size-10 items-center justify-center rounded-pill bg-panel text-muted"><Icon name="sending" /></span>
        <span className="text-ui font-medium text-ink">{t("study.add_file")}</span>
        <span className="text-meta text-muted">{t("study.drop_hint")}</span>
        <input type="file" accept={ACCEPT} disabled={view.busy} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void controller.upload(file, undefined, false); }} className="sr-only" />
      </label>
      <p className="text-meta text-muted">{t("study.file_help")}</p>
      <span className="flex flex-wrap gap-2"><Button size="sm" tone="ghost" aria-expanded={pasting} onClick={() => setPasting((open) => !open)}><Icon name="notes" size={16} />{t("study.paste")}</Button></span>
      {pasting && <form className="flex flex-col items-start gap-3" onSubmit={(e) => { e.preventDefault(); void controller.addText(title.trim(), text).then(() => { if (!controller.getView().error) { setTitle(""); setText(""); } }); }}>
          <label className="flex w-full flex-col gap-2 text-ui text-ink">{t("study.source_title")}<input required maxLength={200} value={title} disabled={view.busy} onChange={(e) => setTitle(e.target.value)} className={FIELD_LOOK} /></label>
          <label className="flex w-full flex-col gap-2 text-ui text-ink">{t("study.paste_label")}<textarea required maxLength={200000} rows={6} disabled={view.busy} value={text} onChange={(e) => setText(e.target.value)} className={FIELD_LOOK} /></label>
          <Button type="submit" disabled={view.busy || !title.trim() || !text.trim()}>{t("study.add_text")}</Button>
        </form>}
      <section className="flex flex-col items-start gap-3" aria-label={t("study.saved_notes")}>
        <Button size="sm" tone="ghost" disabled={view.busy} onClick={() => { void controller.loadNotes(); }}><Icon name="notes" size={16} />{t("study.choose_note")}</Button>
        {view.notes.map((note) => <div key={note.id} className="flex flex-col items-start gap-2"><Button size="sm" disabled={view.busy} onClick={() => { if (note.private) setNoteConfirm(note.id); else void controller.importNote(note, false); }}>{note.title ?? t("study.private_note")}</Button>{noteConfirm === note.id && <><p className="text-ui">{t("study.note_confirm")}</p><div className="flex gap-2"><Button size="sm" disabled={view.busy} onClick={() => { setNoteConfirm(null); void controller.importNote(note, true); }}>{t("study.import_note")}</Button><Button size="sm" tone="ghost" onClick={() => setNoteConfirm(null)}>{t("action.cancel")}</Button></div></>}</div>)}
      </section>
    </div>
    <section className="flex flex-col gap-2" aria-labelledby="study-library">
      <h2 id="study-library" className="px-1 text-label font-medium text-faint">{t("study.library")}</h2>
      {view.sources.length === 0 && view.status === "ready" && <EmptyState message={t("study.empty")} />}
      <ul className="flex flex-col" aria-label={t("study.library")}>{view.sources.map((source) => <li key={source.source_id} className="flex flex-col gap-2 rounded-control px-1 py-1">
        <div className="flex items-center gap-3">
          <Button tone="ghost" disabled={view.busy} onClick={() => { if (source.private) setConfirm(source.source_id); else void controller.open(source.source_id); }}>{"title" in source ? source.title : t("study.private_source")}</Button>
          <span className="flex-1" />
          {"state" in source && <p className="text-meta text-muted">{t(`study.source.${source.state}`)}</p>}
        </div>
        {confirm === source.source_id && <div className="flex flex-col items-start gap-2 px-4"><p className="text-ui">{t("study.private_confirm")}</p><div className="flex gap-2"><Button size="sm" onClick={() => { setConfirm(null); void controller.open(source.source_id); }}>{t("study.open_private")}</Button><Button size="sm" tone="ghost" onClick={() => setConfirm(null)}>{t("action.cancel")}</Button></div></div>}
      </li>)}</ul>
    </section>
    {/* Before any material the tools show what they will do, greyed (STU-21). */}
    {view.sources.length === 0 && view.status === "ready" && <GenerateTools disabled empty onPick={() => undefined} />}
    <MySets sets={view.sets} busy={view.busy} onOpen={(set) => { void controller.openSet(set); }} />
    {jobs(view.jobs)}
  </section>;

  // --- an opened material: the material beside its study tools ----------------------------------------------------
  const source = view.source;
  const chats = view.aids.filter((aid) => aid.kind === "chat");
  const shown = view.aid !== null && view.aid !== undefined && tabOf(view.aid.kind) === tab ? view.aid : null;
  const setsHere = view.sets.filter((set) => set.kind !== "chapters" && set.sources.some((s) => s.source_id === source.source_id));
  const chapters = view.aids.find((aid) => aid.kind === "chapters" && aid.status === "ready")?.chapters ?? null;
  const syllabi = view.sources.flatMap((s) => s.source_id !== source.source_id && "title" in s && s.state === "ready" ? [{ source_id: s.source_id, revision: s.revision, title: s.title }] : []);
  const pick = (next: GenerateTool) => { setTool(next); if (view.materialTopics.length === 0) void controller.loadMaterialTopics(); };

  // The split needs the screen's own width (a container query), not the window's: the sidebar and the board take room.
  // The settings dialog sits outside the container query: a size container would trap its fixed overlay.
  return <><section className="@container h-full min-h-0 w-full" aria-labelledby="study-heading"><div className="flex h-full min-h-0 w-full flex-col overflow-y-auto @4xl:flex-row @4xl:overflow-hidden">
    {/* The material */}
    <div className="flex min-w-0 flex-col @4xl:min-h-0 @4xl:flex-1">
      <header className="flex min-h-14 shrink-0 items-center gap-2 px-4">
        <IconButton icon="go-back" size="sm" label={t("study.back")} onClick={() => controller.close()} />
        <div className="flex min-w-0 flex-col">
          <h1 id="study-heading" className="truncate text-ui font-semibold text-ink">{source.title}</h1>
          <p className="text-meta text-muted">{source.revision > 1 && <>{t("study.revision", { revision: source.revision })} · </>}{t(`study.source.${source.state}`)}</p>
        </div>
        <span className="flex-1" />
        {view.availableRevisions.length > 1 && <label className="flex items-center gap-2 text-meta text-muted">{t("study.choose_revision")}<select className={FIELD_LOOK} value={source.revision} onChange={(e) => { void controller.open(source.source_id, Number(e.target.value)); }}>{view.availableRevisions.map((rev) => <option key={rev} value={rev}>{rev}</option>)}</select></label>}
      </header>
      <div className="flex flex-col gap-4 px-6 pb-6 @4xl:min-h-0 @4xl:flex-1 @4xl:overflow-y-auto">
        {source.state !== "ready" && <Notice message={source.state === "partial" ? t("study.partial", { units: source.unreadable_units.join(", ") }) : t(`study.source.${source.state}`)} />}
        {source.kind === "recording" && <Notice message={t("study.recording_help")} />}
        {source.state === "queued" && <span><Button tone="primary" disabled={view.busy} onClick={() => { void controller.startExtraction(source.kind === "recording"); }}>{t("study.start_extraction")}</Button></span>}
        {source.state === "partial" && <label className="flex min-h-11 items-center gap-2 text-ui text-ink"><input type="checkbox" checked={readableConfirmed} onChange={(e) => setReadableConfirmed(e.target.checked)} />{t("study.confirm_readable")}</label>}
        {source.state === "uploading" && <label className="flex flex-col gap-2 text-ui text-ink">{t("study.resume_upload")}<input type="file" accept={ACCEPT} disabled={view.busy} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void controller.upload(file, source, false); }} /></label>}
        <span><Button size="sm" tone="ghost" aria-expanded={managing} onClick={() => setManaging((open) => !open)}>{t("study.manage")}</Button></span>
        {managing && <div className="flex flex-col items-start gap-3 rounded-card bg-chrome p-4">
            {["pdf", "document", "slides", "photo", "recording"].includes(source.kind) && <label className="flex flex-col gap-2 text-ui text-ink">{t("study.replace_file")}<input type="file" accept={ACCEPT} disabled={view.busy} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void controller.upload(file, source, false, true); }} /></label>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={view.busy} onClick={() => { setCorrectedText(view.chunks.map((c) => c.text).join("\n\n")); setCorrecting(true); }}>{t("study.correct_text")}</Button>
              <Button size="sm" disabled={view.busy} onClick={() => { void controller.markPrivate(); }}>{t(source.private ? "study.make_public" : "study.make_private")}</Button>
              <Button size="sm" disabled={view.busy} onClick={() => { void controller.refreshOpened(); }}>{t("study.refresh")}</Button>
              <Button size="sm" tone="danger" disabled={view.busy} onClick={() => setDeleting(true)}>{t("study.delete")}</Button>
            </div>
        </div>}
        {correcting && <form className="flex flex-col items-start gap-3" onSubmit={(e) => { e.preventDefault(); void controller.correctText(correctedText).then(() => { if (!controller.getView().error) setCorrecting(false); }); }}><label className="flex w-full flex-col gap-2 text-ui text-ink">{t("study.correct_help")}<textarea rows={10} required maxLength={200000} className={FIELD_LOOK} value={correctedText} onChange={(e) => setCorrectedText(e.target.value)} /></label><div className="flex gap-2"><Button type="submit" tone="primary" disabled={view.busy || !correctedText.trim()}>{t("study.save_revision")}</Button><Button tone="ghost" onClick={() => setCorrecting(false)}>{t("action.cancel")}</Button></div></form>}
        {deleting && <div className="flex flex-col items-start gap-2"><p className="text-ui">{t("study.delete_confirm")}</p><div className="flex gap-2"><Button tone="danger" disabled={view.busy} onClick={() => { void controller.remove(); }}>{t("study.delete_yes")}</Button><Button tone="ghost" onClick={() => setDeleting(false)}>{t("action.cancel")}</Button></div></div>}
        <div ref={passage} tabIndex={-1} className="mx-auto flex w-full max-w-2xl flex-col gap-4 rounded-card border border-line bg-canvas px-8 py-7 outline-none" aria-label={t("study.source_passage")}>
          {citation && <span><Button size="sm" onClick={() => { setCitation(null); returnFocus.current?.focus(); }}>{t("study.back_to_aid")}</Button></span>}
          {pageImage && <figure className="flex flex-col gap-2"><img className="h-auto w-full" src={pageImage.url} alt={t("study.page_image", { page: pageImage.page })} /><figcaption className="text-meta text-muted">{t("study.page_image", { page: pageImage.page })}</figcaption></figure>}
          {source.kind === "recording" && view.chunks.length > 0 && <RecordingPlayer chunks={view.chunks} chapters={chapters} playhead={view.playhead} busy={view.busy}
            loadMedia={() => controller.loadMedia()} onSeek={(ms) => controller.seek(ms)} onCite={cite}
            canMakeChapters={ready} onMakeChapters={() => { void controller.generate("chapters", 10, readableConfirmed, preferCloud); }} />}
          {source.kind !== "recording" && view.chunks.map((chunk) => <article key={chunk.chunk_id} className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <p className="text-meta text-faint">{chunk.locator.kind === "time" ? t("study.timestamp", { start: `${Math.floor(chunk.locator.start_ms / 60000)}:${String(Math.floor(chunk.locator.start_ms / 1000) % 60).padStart(2, "0")}`, end: `${Math.floor(chunk.locator.end_ms / 60000)}:${String(Math.floor(chunk.locator.end_ms / 1000) % 60).padStart(2, "0")}` }) : t("study.location", { kind: "page" in chunk.locator ? "page" : "slide" in chunk.locator ? "slide" : "part", number: "page" in chunk.locator ? chunk.locator.page : "slide" in chunk.locator ? chunk.locator.slide : chunk.ordinal + 1 })}{revisionTag(chunk.revision)}</p>
              {"page" in chunk.locator && <Button size="sm" tone="ghost" disabled={view.busy} onClick={() => { if ("page" in chunk.locator) showPage(chunk.locator.page, chunk.revision, chunk.source_id); }}>{t("study.show_page", { page: chunk.locator.page })}</Button>}
            </div>
            <p className="whitespace-pre-wrap break-words text-body text-ink">{citation?.chunk_id === chunk.chunk_id ? <>{Array.from(chunk.text).slice(0, citation.start).join("")}<mark className="bg-highlight-soft text-ink underline decoration-highlight-line">{Array.from(chunk.text).slice(citation.start, citation.end).join("")}</mark>{Array.from(chunk.text).slice(citation.end).join("")}</> : chunk.text}</p>
          </article>)}
        </div>
      </div>
    </div>

    {/* The study tools */}
    <aside aria-label={t("study.aids")} className="flex w-full shrink-0 flex-col border-t border-line bg-canvas @4xl:min-h-0 @4xl:w-[28rem] @4xl:border-t-0 @4xl:border-s @6xl:w-[32rem]">
      <div role="tablist" aria-label={t("study.aids")} className="flex min-h-14 shrink-0 items-center gap-1 overflow-x-auto border-b border-line px-3">
        {TABS.map((name) => <Button key={name} role="tab" size="sm" tone="ghost" aria-selected={tab === name} onClick={() => setTab(name)}>{t(`study.tab.${name}`)}</Button>)}
      </div>
      <div role="tabpanel" aria-label={t(`study.tab.${tab}`)} className="flex flex-col gap-4 px-5 py-4 @4xl:min-h-0 @4xl:flex-1 @4xl:overflow-y-auto">
        {status}
        {jobs(view.jobs.filter((j) => j.sources.some((s) => s.source_id === source.source_id)))}
        <p className="text-meta text-muted">{t("study.grounded_notice")}</p>
        {tab === "generate" && !shown && <>
          <GenerateTools disabled={view.busy || !ready} onPick={pick} />
          <MySets sets={setsHere} busy={view.busy} heading={false} onOpen={(set) => { void controller.showAid(set.aid_id); }} />
          <Button size="sm" tone="ghost" disabled={view.busy || source.state !== "ready" || !view.followCurrent} onClick={() => { void controller.loadTopics(); }}>{t("study.find_topics")}</Button>
          {view.topics.length > 0 && <section className="flex flex-col gap-3" aria-label={t("study.suggested_topics")}><p className="text-meta text-muted">{t("study.topic_help")}</p>{view.topics.map((topic) => <div key={topic.node_id} className="flex flex-col gap-2"><p className="text-ui font-semibold">{topic.title}</p><div className="flex flex-wrap gap-2">{openTopic && <Button size="sm" onClick={() => openTopic(topic.node_id)}>{t("study.topic_guide")}</Button>}{onPractice && <Button size="sm" onClick={() => onPractice(topic.subject, topic.kc_ids)}>{t("study.topic_practice")}</Button>}{openLesson && topic.lesson_ids.map((lesson, i) => <Button size="sm" key={lesson} onClick={() => openLesson(lesson)}>{t("study.topic_lesson", { number: i + 1 })}</Button>)}</div></div>)}</section>}
          <fieldset className="flex flex-col gap-2"><legend className="text-ui font-semibold">{t("study.extra_sources")}</legend><p className="text-meta text-muted">{t("study.extra_sources_help")}</p>{view.sources.filter((s) => s.source_id !== source.source_id && (!("state" in s) || s.state === "ready")).map((s) => <div key={s.source_id} className="flex flex-col gap-2"><label className="flex min-h-11 items-center gap-2 text-ui"><input type="checkbox" checked={view.selections.some((x) => x.source_id === s.source_id)} disabled={view.busy || (view.selections.length >= 8 && !view.selections.some((x) => x.source_id === s.source_id))} onChange={() => { if (s.private && !view.selections.some((x) => x.source_id === s.source_id)) setExtraConfirm(s.source_id); else void controller.selectExtra(s.source_id); }} />{"title" in s ? s.title : t("study.private_source")}</label>{extraConfirm === s.source_id && <><p className="text-ui">{t("study.private_confirm")}</p><div className="flex gap-2"><Button size="sm" onClick={() => { setExtraConfirm(null); void controller.selectExtra(s.source_id); }}>{t("study.open_private")}</Button><Button size="sm" tone="ghost" onClick={() => setExtraConfirm(null)}>{t("action.cancel")}</Button></div></>}</div>)}</fieldset>
        </>}
        {tab === "chat" && chats.length > 0 && <ul className="flex flex-col" aria-label={t("study.aids")}>{chats.map((aid) => <li key={aid.aid_id}><Button size="sm" tone="ghost" aria-pressed={view.aid?.aid_id === aid.aid_id} disabled={view.busy} onClick={() => { void controller.showAid(aid.aid_id); }}>{aid.prompt ?? aid.title}{aid.status === "stale" ? ` · ${t("study.stale")}` : ""}</Button></li>)}</ul>}
        {shown && <article className="flex flex-col gap-4">
          {tab === "generate" && <span><Button size="sm" tone="ghost" onClick={() => controller.hideAid()}><Icon name="go-back" size={16} />{t("study.all_tools")}</Button></span>}
          {tab === "generate" && <h2 className="text-ui font-semibold text-ink">{t(`study.tool.${shown.kind}`)} · {shown.title}</h2>}
          {shown.prompt && <p className="whitespace-pre-wrap rounded-card bg-panel px-4 py-3 text-ui font-medium">{shown.prompt}</p>}
          {shown.kind === "audio_overview" && <><div className="flex flex-wrap gap-2">{view.reading ? <Button onClick={() => controller.stopReading()}>{t("study.stop_audio")}</Button> : <Button tone="primary" disabled={!view.canSpeak || shown.status !== "ready"} onClick={() => { void controller.playOverview(); }}>{t("study.play_audio")}</Button>}</div>{!view.canSpeak && <Notice message={t("study.voice_unavailable")} />}<p role="status" className="text-meta text-muted">{view.reading ? t("study.reading_claim", { number: view.spokenClaim + 1 }) : t("study.audio_local")}</p></>}
          {shown.status === "stale" && <Notice message={t("study.stale_help")} />}
          {!view.deck && !view.quiz && shown.claims.map((c, i) => claim(c, String(i)))}
          {/* After a chat answer, at most two next steps (UXS-68): cards from it, or a step explained again. */}
          {shown.kind === "chat" && shown.status === "ready" && <FollowUpChips disabled={view.busy || !ready}
            chips={followUps(["flashcards", "explain_step"], (kind) => t(`followup.${kind}`))}
            onChoose={(chip) => {
              if (chip.kind === "flashcards") { setTab("generate"); void controller.generate("flashcards", 10, readableConfirmed, preferCloud); }
              else { setChatPrompt(t("followup.ask.explain_step")); ask.current?.focus(); }
            }} />}
          {view.deck && (!card ? <EmptyState message={t("study.cards_done")} /> : <section className="flex flex-col gap-4 rounded-card border border-line p-5" aria-label={t("study.flashcard")}>
            {claim(card.front)}
            {revealed ? <>{claim(card.back)}<div className="flex flex-wrap gap-2">{(["again", "hard", "good", "easy"] as const).map((rating) => <Button key={rating} size="sm" disabled={view.busy || shown.status === "stale"} onClick={() => { void controller.rate(card, rating); }}>{t(`study.rating.${rating}`)}</Button>)}</div></> : <span><Button tone="primary" onClick={() => setRevealed(true)}>{t("study.reveal")}</Button></span>}
          </section>)}
          {view.quiz && <form ref={quizBox} className="flex flex-col gap-5" onSubmit={(e) => { e.preventDefault(); void controller.submit(answers); }}>
            {view.quiz.items.map((item, i) => <fieldset key={item.item_id} data-item={i} disabled={view.busy || !!view.result || view.quiz?.status !== "ready"} className="flex flex-col gap-3"><legend className="text-meta font-medium text-muted">{t("study.question", { number: i + 1 })}{item.type === "multi_select" ? ` · ${t("study.choose_all")}` : ""}</legend>{claim(item.stem)}
              {!view.result && <HelpChips disabled={view.busy} onHelp={(kind) => help(kind, item.stem.text)} />}
              {item.type === "choice" ? item.options?.map((option) => <label key={option.option_id} className="flex min-h-11 items-center gap-3 rounded-control border border-line px-4 py-2 text-ui text-ink has-checked:border-ink"><input type="radio" name={item.item_id} value={option.option_id} checked={answers[item.item_id] === option.option_id} onChange={() => answer(item.item_id, option.option_id, i)} /><span><PackInline text={option.text} /></span></label>)
                : item.type === "multi_select" ? item.options?.map((option) => { const chosen = picked(answers[item.item_id]); return <label key={option.option_id} className="flex min-h-11 items-center gap-3 rounded-control border border-line px-4 py-2 text-ui text-ink has-checked:border-ink"><input type="checkbox" checked={chosen.includes(option.option_id)} onChange={() => answer(item.item_id, (chosen.includes(option.option_id) ? chosen.filter((x) => x !== option.option_id) : [...chosen, option.option_id]).join(","), i)} /><span><PackInline text={option.text} /></span></label>; })
                : item.type === "true_false" ? (["true", "false"] as const).map((value) => <label key={value} className="flex min-h-11 items-center gap-3 rounded-control border border-line px-4 py-2 text-ui text-ink has-checked:border-ink"><input type="radio" name={item.item_id} value={value} checked={answers[item.item_id] === value} onChange={() => answer(item.item_id, value, i)} />{t(`study.${value}`)}</label>)
                : <label className="flex flex-col gap-2 text-ui">{t(item.type === "fill_blank" ? "study.fill_blank" : "study.answer")}<input className={FIELD_LOOK} value={answers[item.item_id] ?? ""} onChange={(e) => answer(item.item_id, e.target.value, i, false)} onBlur={() => { void controller.saveDraft(answers, i); }} /></label>}
            </fieldset>)}
            {!view.result && <span><Button type="submit" tone="primary" disabled={view.busy || view.quiz.status !== "ready"}>{t("study.submit")}</Button></span>}
            {view.result && <section className="flex flex-col gap-3" aria-label={t("study.results")}><p className="text-meta text-muted">{t("study.no_mastery")}</p>{view.result.results.map((r) => {
              const item = view.quiz?.items.find((x) => x.item_id === r.item_id);
              const missed = r.verdict === "incorrect" || r.verdict === "partial";
              const open = !missed || round >= 2 || shownAnswers.includes(r.item_id);
              return <div key={r.item_id} className="flex flex-col gap-2"><p className="text-ui font-semibold">{t(`study.verdict.${r.verdict}`)}</p>
                {"explanation" in r && open && <><p className="text-meta text-muted">{r.label}</p>{claim(r.explanation)}</>}
                {"explanation" in r && !open && <><p className="text-meta text-muted">{t("study.not_yet")}</p>{item && <HelpChips disabled={view.busy} onHelp={(kind) => help(kind, item.stem.text)} />}<span><Button size="sm" tone="ghost" onClick={() => setShownAnswers((now) => [...now, r.item_id])}>{t("study.show_answer")}</Button></span></>}
              </div>;
            })}{round < 2 && view.result.results.some((r) => (r.verdict === "incorrect" || r.verdict === "partial") && !shownAnswers.includes(r.item_id)) && <span><Button tone="primary" disabled={view.busy} onClick={() => controller.clearResult()}>{t("study.try_again")}</Button></span>}</section>}
          </form>}
        </article>}
      </div>
      {/* The ask box: always here, whichever tool is open */}
      <form className="flex shrink-0 flex-col gap-3 border-t border-line px-4 pt-3 pb-4" onSubmit={(e) => { e.preventDefault(); void controller.generate("chat", 10, readableConfirmed, preferCloud, chatPrompt).then(() => { if (!controller.getView().error) setChatPrompt(""); }); }}>
        <HelpChips disabled={view.busy || !ready} onHelp={(kind) => { setChatPrompt(t(`help.ask.${kind}`)); setTab("chat"); ask.current?.focus(); }} />
        <ComposerShell send={<IconButton type="submit" tone="action" icon="send" tip="above" label={t("study.ask_material")} disabled={view.busy || !chatPrompt.trim() || !ready} />}
          below={<p className="px-1 pb-1 text-meta text-faint">{t("study.ask_grounded")}</p>}>
          <label htmlFor="study-ask" className="sr-only">{t("study.chat_prompt")}</label>
          <textarea id="study-ask" ref={ask} rows={2} required maxLength={4000} placeholder={t("study.ask_placeholder")} className="w-full resize-none bg-transparent px-1 text-body text-ink outline-none placeholder:text-placeholder" value={chatPrompt} onChange={(e) => setChatPrompt(e.target.value)} />
        </ComposerShell>
      </form>
    </aside>
  </div></section>
  <GenerateDialog tool={tool} topics={view.materialTopics} syllabi={syllabi} busy={view.busy} error={view.error && !view.safetyTemplate ? errorText(view.error) : null} onClose={() => setTool(null)}
        onGenerate={(chosen, request) => { void controller.generate(chosen, request.count, readableConfirmed, preferCloud, undefined, request.settings).then(() => { if (!controller.getView().error) setTool(null); }); }} /></>;
}
