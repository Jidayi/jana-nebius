// The subject map, Learn (UXS-22, LRN-34, DSN-23; direction A "Studio"): the 56 px header names the place and carries
// the subject switch; under it the subject in display type with how many of its topics are secure, the lesson in
// progress when there is one ("Continue"), then one subject's topics as cards grouped by syllabus section. Each card
// shows the first TABLE UXS-22a label whose rule holds over its KCs (fill, pattern, icon and word, never colour alone)
// beside the mastery ring, a segmented bar of its KCs by LRN-34 band with the counts in words, and how many lessons it
// has. A topic with no progress shows only its mark ("Not started"), and a topic with no lessons no lesson count. Selecting a card opens the topic sheet beside the cards: every KC with its own TABLE LRN-09a label, the topic's
// lessons, practice and "Ask the tutor about this", "Check my mastery" on a KC that is nearly secure and "I already
// know this" on one that is not secure. An action the app cannot offer yet (no handler) is not shown, never a dead
// button. States: canonical, loading (skeleton cards), empty (no pack, or no topics), error-retriable (the read failed)
// and the unverified pack. When the map carries board syllabuses (CUR-06, D113) a "Syllabus" switch shows every topic
// or one syllabus's: a chosen syllabus hides the topics outside it (and a section left empty), each tile shows its
// codes, and a line under the switch names every board shown as not endorsing Jana. The topic sheet lists the topic's
// syllabus points, "Partly covers" on a partial one.
import { useEffect, useId, useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";
import { syllabusCodes, topicLabel, type MapKc, type MapSyllabus, type MapTopic, type MapView, type SubjectMapController } from "@jana/client-core";
import { ScreenHeader } from "../frame/Frame.js";
import { Icon } from "../icons.js";
import { useT } from "../i18n.js";
import { Button, EmptyState, ErrorState, IconButton, ProgressBar, SegmentedControl, Skeleton, SuggestionChip } from "../primitives/index.js";
import { MasteryMark, MasteryRing, SegmentedBar, useCountsText } from "./Mastery.js";

export interface MapActions {
  onStartLesson?: (lessonId: string) => void;
  onPractise?: (topic: MapTopic) => void;
  onAsk?: (topic: MapTopic) => void;
  /** "Check my mastery" (`now` false) and "I already know this" (`now` true), both the mastery check of UXS-41. */
  onMasteryCheck?: (kc: MapKc, now: boolean) => void;
}

export interface SubjectChoice {
  subjectId: string;
  name: string;
}

/** The lesson the student is part way through, offered above the topics with "Continue". */
export interface LessonInProgress {
  lessonId: string;
  title: string;
  /** The part shown, from 1, and how many parts the lesson has. */
  part: number;
  parts: number;
}

/** Most options a segmented control holds (DSN-12); more subjects than this are chips. */
const SEGMENTS_MAX = 4;

/** The value the syllabus switch uses for "All topics" (scheme ids never start with a dash). */
const ALL = "-all";

function Tile({ topic, onOpen, selected, onStartLesson, syllabus }: { topic: MapTopic; onOpen: (topic: MapTopic, from: HTMLButtonElement) => void; selected: boolean; onStartLesson: MapActions["onStartLesson"]; syllabus: MapSyllabus | null }) {
  const t = useT();
  const codes = syllabus === null ? [] : syllabusCodes(topic, syllabus.scheme).map((p) => p.code);
  const counts = useCountsText()(topic.kcs);
  const label = topicLabel(topic.kcs.map((k) => k.state));
  // An untouched topic says so once, with its mark; the counts, the bar and the ring appear with the first progress.
  const started = topic.kcs.some((k) => k.band !== "not_started");
  return (
    <li className="flex flex-col gap-2">
      <button
        type="button"
        data-topic-id={topic.node_id}
        data-label={label}
        aria-expanded={selected}
        onClick={(e) => onOpen(topic, e.currentTarget)}
        className="jana-press flex w-full flex-1 flex-col items-stretch gap-3 rounded-card border border-line bg-canvas p-5 text-start hover:bg-wash aria-expanded:border-line-strong aria-expanded:bg-wash"
      >
        <span className="flex items-start justify-between gap-3">
          <span className="text-body font-semibold text-ink">{topic.title}</span>
          <span aria-hidden="true" className="mt-1 shrink-0 text-faint"><Icon name="expand" size={16} /></span>
        </span>
        {syllabus !== null && codes.length > 0 && (
          <span className="text-meta text-muted" data-syllabus-codes={codes.join(" ")}>{t("map.syllabus.codes", { code: syllabus.syllabus_code, points: codes.join(", ") })}</span>
        )}
        {started && (
          <>
            <span className="text-meta text-muted">{counts}</span>
            <SegmentedBar kcs={topic.kcs} />
          </>
        )}
        <span className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
          <span className="flex items-center gap-2">
            {started && <MasteryRing kcs={topic.kcs} />}
            <MasteryMark state={label} />
          </span>
          {topic.lessons.length > 0 && <span className="text-meta text-faint">{t("map.lessons", { count: topic.lessons.length })}</span>}
        </span>
      </button>
      {onStartLesson !== undefined && topic.lessons.map((lesson) => (
        <span key={lesson.lesson_id} className="flex"><Button size="sm" tone="ghost" onClick={() => onStartLesson(lesson.lesson_id)}><Icon name="learn" size={16} />{t("map.open_lesson", { title: lesson.title })}</Button></span>
      ))}
    </li>
  );
}

function TopicSheet({ topic, actions, onClose, syllabuses }: { topic: MapTopic; actions: MapActions; onClose: () => void; syllabuses: MapSyllabus[] }) {
  const t = useT();
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [topic.node_id]);
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };
  return (
    <section role="dialog" aria-modal="false" aria-labelledby={id} onKeyDown={onKey} data-topic-sheet={topic.node_id}
      className="jana-reveal flex flex-col gap-5 rounded-card border border-line bg-canvas p-5 lg:sticky lg:top-4">
      <div className="flex items-start justify-between gap-2">
        <h2 id={id} ref={heading} tabIndex={-1} className="text-heading text-ink">{topic.title}</h2>
        <span className="-me-2 -mt-1"><IconButton icon="dismiss" size="sm" label={t("sheet.close")} onClick={onClose} /></span>
      </div>
      <div className="flex flex-col gap-3">
        {topic.lessons.length === 0 ? (
          <p className="text-ui text-muted">{t("sheet.no_lesson")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {topic.lessons.map((lesson) => (
              <li key={lesson.lesson_id} className="flex flex-col gap-2 rounded-control bg-panel p-3" data-lesson-id={lesson.lesson_id}>
                <span className="text-ui text-ink">{t("sheet.lesson_meta", { title: lesson.title, minutes: lesson.estimated_minutes })}</span>
                {actions.onStartLesson !== undefined && (
                  <span>
                    <Button tone="primary" size="sm" onClick={() => actions.onStartLesson?.(lesson.lesson_id)}>
                      <Icon name="learn" size={16} />
                      {t("sheet.start_lesson")}
                    </Button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {(actions.onPractise !== undefined || actions.onAsk !== undefined) && (
          <div className="flex flex-wrap gap-2">
            {actions.onPractise !== undefined && (
              <Button onClick={() => actions.onPractise?.(topic)}>
                <Icon name="practice" size={16} />
                {t("sheet.practise")}
              </Button>
            )}
            {actions.onAsk !== undefined && (
              <Button onClick={() => actions.onAsk?.(topic)}>
                <Icon name="ask" size={16} />
                {t("sheet.ask")}
              </Button>
            )}
          </div>
        )}
      </div>
      <SyllabusPoints topic={topic} syllabuses={syllabuses} />
      <div className="flex flex-col gap-2">
        <h3 className="text-label text-faint">{t("sheet.kcs")}</h3>
        <ul className="flex flex-col divide-y divide-line">
          {topic.kcs.map((kc) => (
            <li key={kc.kc_id} data-kc-id={kc.kc_id} data-state={kc.state} className="flex flex-col gap-2 py-3">
              <span className="text-ui text-ink">{kc.statement}</span>
              <span className="flex flex-wrap items-center gap-2">
                <MasteryMark state={kc.state} />
                {kc.state === "ready_to_check" && actions.onMasteryCheck !== undefined && (
                  <Button size="sm" onClick={() => actions.onMasteryCheck?.(kc, false)}>{t("sheet.check_mastery")}</Button>
                )}
                {kc.state !== "mastered" && actions.onMasteryCheck !== undefined && (
                  <Button size="sm" tone="ghost" onClick={() => actions.onMasteryCheck?.(kc, true)}>{t("sheet.already_know")}</Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** The topic's board syllabus points in the sheet, by syllabus; nothing when it has none. */
function SyllabusPoints({ topic, syllabuses }: { topic: MapTopic; syllabuses: MapSyllabus[] }) {
  const t = useT();
  const rows = syllabuses.flatMap((s) => syllabusCodes(topic, s.scheme).map((p) => ({ syllabus: s, point: p })));
  if (rows.length === 0) return null;
  return (
    <div className="flex flex-col gap-2" data-syllabus-points>
      <h3 className="text-label text-faint">{t("sheet.syllabus")}</h3>
      <ul className="flex flex-col gap-1">
        {rows.map(({ syllabus, point }) => (
          <li key={`${point.scheme}:${point.code}`} className="text-ui text-ink" data-coverage={point.coverage}>
            {t("sheet.syllabus_point", { board: syllabus.board, code: syllabus.syllabus_code, point: point.code })}
            {point.coverage === "partial" && <span className="text-muted">{" · "}{t("sheet.partly_covers")}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "All topics" or one syllabus, and the line naming every board shown as not endorsing Jana (CUR-06). */
function SyllabusSwitch({ syllabuses, value, onChange }: { syllabuses: MapSyllabus[]; value: string | null; onChange: (scheme: string | null) => void }) {
  const t = useT();
  const options = [{ value: ALL, label: t("map.syllabus.all") }, ...syllabuses.map((s) => ({ value: s.scheme, label: t("map.syllabus.option", { board: s.board, code: s.syllabus_code }) }))];
  const boards = [...new Set(syllabuses.map((s) => s.board))];
  const pick = (v: string) => onChange(v === ALL ? null : v);
  return (
    <div className="flex flex-col gap-2" data-syllabus-switch={value ?? ALL}>
      {options.length <= SEGMENTS_MAX ? (
        <SegmentedControl label={t("map.syllabus")} value={value ?? ALL} onChange={pick} options={options} />
      ) : (
        <div role="group" aria-label={t("map.syllabus")} className="flex flex-wrap gap-2">
          {options.map((o) => <SuggestionChip key={o.value} aria-pressed={o.value === (value ?? ALL)} onClick={() => pick(o.value)}>{o.label}</SuggestionChip>)}
        </div>
      )}
      {boards.map((board) => <p key={board} className="text-meta text-faint" data-not-endorsed={board}>{t("map.not_endorsed", { board })}</p>)}
    </div>
  );
}

function Loading() {
  const t = useT();
  return (
    <div role="status" aria-busy="true" className="flex flex-col gap-4" data-map-loading>
      <span className="sr-only">{t("map.loading")}</span>
      <span className="block h-6 w-64"><Skeleton lines={1} /></span>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-4">
        {[0, 1, 2, 3].map((i) => (
          <li key={i} className="flex min-h-40 flex-col justify-center rounded-card border border-line bg-canvas p-5">
            <Skeleton lines={3} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The subject switch in the header: a segmented control, or chips when there are more subjects than it holds. */
function SubjectSwitch({ subjects, value, onSubject }: { subjects: SubjectChoice[]; value: string | null; onSubject?: ((subjectId: string) => void) | undefined }) {
  const t = useT();
  if (subjects.length < 2) return null;
  if (subjects.length <= SEGMENTS_MAX) {
    return <SegmentedControl label={t("map.subjects")} value={value ?? ""} onChange={(id) => onSubject?.(id)}
      options={subjects.map((s) => ({ value: s.subjectId, label: s.name }))} />;
  }
  return (
    <div role="group" aria-label={t("map.subjects")} className="flex flex-wrap gap-2">
      {subjects.map((s) => <SuggestionChip key={s.subjectId} aria-pressed={s.subjectId === value} onClick={() => onSubject?.(s.subjectId)}>{s.name}</SuggestionChip>)}
    </div>
  );
}

/** The map from its view: the gallery and the tests render this directly. */
export function SubjectMapContent({ view, subjects = [], onSubject, onSyllabus, onRetry, actions = {}, initialTopic, inProgress = null, onContinue }: {
  view: MapView;
  subjects?: SubjectChoice[];
  onSubject?: (subjectId: string) => void;
  /** The syllabus switch's choice, kept by the controller; without it the choice is this view's own. */
  onSyllabus?: (scheme: string | null) => void;
  onRetry?: () => void;
  actions?: MapActions;
  /** A topic whose sheet is open from the start (the gallery's topic-sheet state). */
  initialTopic?: string;
  /** The lesson part way through in this subject, offered with "Continue". */
  inProgress?: LessonInProgress | null;
  onContinue?: (lessonId: string) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState<{ id: string; from: HTMLButtonElement | null } | null>(initialTopic === undefined ? null : { id: initialTopic, from: null });
  const [ownSyllabus, setOwnSyllabus] = useState<string | null>(view.syllabus ?? null);
  const map = view.map;
  const syllabuses = map?.syllabuses ?? [];
  const chosen = onSyllabus !== undefined ? view.syllabus ?? null : ownSyllabus;
  const syllabus = syllabuses.find((s) => s.scheme === chosen) ?? null;
  const chooseSyllabus = (scheme: string | null) => (onSyllabus !== undefined ? onSyllabus(scheme) : setOwnSyllabus(scheme));
  // With a syllabus chosen, only the topics it maps, and only the sections that keep one (D113).
  const sections = (map?.sections ?? [])
    .map((s) => (syllabus === null ? s : { ...s, topics: s.topics.filter((tp) => syllabusCodes(tp, syllabus.scheme).length > 0) }))
    .filter((s) => s.topics.length > 0);
  const topics = sections.flatMap((s) => s.topics);
  const topic = open === null ? null : topics.find((tp) => tp.node_id === open.id) ?? null;
  const secure = topics.filter((tp) => topicLabel(tp.kcs.map((k) => k.state)) === "mastered").length;
  const close = () => {
    open?.from?.focus();
    setOpen(null);
  };
  const body = () => {
    if (view.status === "failed") {
      return <ErrorState message={t("map.failed")} {...(onRetry !== undefined ? { action: { label: t("action.try_again"), onClick: onRetry } } : {})} />;
    }
    if (map === null) return <Loading />;
    if (map.status === "not_installed") return <EmptyState message={t("map.not_installed")} />;
    if (map.status === "unverified") return <ErrorState message={t("map.unverified")} />;
    if (map.sections.length === 0) return <EmptyState message={t("map.no_topics")} />;
    return (
      <div className="flex flex-col gap-8">
        {syllabuses.length > 0 && <SyllabusSwitch syllabuses={syllabuses} value={syllabus?.scheme ?? null} onChange={chooseSyllabus} />}
        {sections.map((section) => (
          <section key={section.node_id} aria-labelledby={`section-${section.node_id}`} data-section-id={section.node_id} className="flex flex-col gap-4">
            <h2 id={`section-${section.node_id}`} className="text-heading text-ink">{section.title}</h2>
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-4">
              {section.topics.map((tp) => (
                <Tile key={tp.node_id} topic={tp} syllabus={syllabus} onStartLesson={actions.onStartLesson} selected={open?.id === tp.node_id} onOpen={(picked, from) => setOpen({ id: picked.node_id, from })} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    );
  };
  return (
    <div className="flex min-h-full flex-col" data-map-status={view.status} data-map-subject={view.subjectId ?? undefined}>
      <ScreenHeader end={<SubjectSwitch subjects={subjects} value={view.subjectId} onSubject={onSubject} />}>
        <span className="text-ui font-semibold text-ink">{t("app.learn")}</span>
      </ScreenHeader>
      <div className="flex-1 px-6 pt-6 pb-12 lg:px-10">
        <div className={`mx-auto grid w-full grid-cols-1 items-start gap-8 ${topic !== null ? "max-w-300 lg:grid-cols-[minmax(0,1fr)_22rem]" : "max-w-240"}`}>
          <div className="flex min-w-0 flex-col gap-8">
            <section aria-labelledby="map-subject" className="flex flex-col gap-4">
              <h1 id="map-subject" className="text-display text-ink">{map?.title ?? t("map.title")}</h1>
              {map !== null && map.status === "ready" && topics.length > 0 && (
                <span className="block max-w-105">
                  <ProgressBar label={t("map.topics_secure")} value={secure} max={topics.length} valueText={t("map.of", { count: secure, total: topics.length })} />
                </span>
              )}
            </section>
            {inProgress !== null && onContinue !== undefined && (
              <section aria-labelledby="map-in-progress" data-in-progress={inProgress.lessonId} className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4 rounded-card border border-line bg-canvas px-6 py-5">
                <div className="flex min-w-0 flex-1 basis-80 flex-col gap-2">
                  <p className="text-label text-faint">{t("map.in_progress")}</p>
                  <h2 id="map-in-progress" className="text-heading text-ink">{inProgress.title}</h2>
                  <span className="block max-w-90">
                    <ProgressBar bare label={t("lesson.parts")} value={inProgress.part} max={inProgress.parts} valueText={t("lesson.progress", { index: inProgress.part, total: inProgress.parts })} />
                  </span>
                </div>
                <Button tone="primary" onClick={() => onContinue(inProgress.lessonId)}>
                  {t("map.continue")}
                  <Icon name="go-next" size={16} />
                </Button>
              </section>
            )}
            {body()}
          </div>
          {topic !== null && <TopicSheet topic={topic} actions={actions} onClose={close} syllabuses={syllabuses} />}
        </div>
      </div>
    </div>
  );
}

/** The map for the unlocked profile: reads on open and on a subject change, re-reads on a mastery change. */
export function SubjectMap({ controller, subjectId, subjects, onSubject, actions, inProgress, onContinue, initialTopic }: {
  controller: SubjectMapController;
  subjectId: string;
  initialTopic?: string;
  subjects?: SubjectChoice[];
  onSubject?: (subjectId: string) => void;
  actions?: MapActions;
  inProgress?: LessonInProgress | null;
  onContinue?: (lessonId: string) => void;
}) {
  const view = useSyncExternalStore(controller.subscribe, controller.getView, controller.getView);
  useEffect(() => {
    void controller.load(subjectId);
  }, [controller, subjectId]);
  return (
    <SubjectMapContent
      view={view}
      onRetry={() => void controller.load(subjectId)}
      onSyllabus={(scheme) => controller.chooseSyllabus(scheme)}
      {...(initialTopic !== undefined ? { initialTopic } : {})}
      {...(subjects !== undefined ? { subjects } : {})}
      {...(onSubject !== undefined ? { onSubject } : {})}
      {...(actions !== undefined ? { actions } : {})}
      {...(inProgress !== undefined ? { inProgress } : {})}
      {...(onContinue !== undefined ? { onContinue } : {})}
    />
  );
}
