import tutorFrame from "./states/app-shell.canonical.json";
import { SettingsPreview } from "./SettingsPreview.js";
import { QuestionDock } from "../src/composer/QuestionDock.js";
import { WorkingEntry } from "../src/board/WorkingEntry.js";
import { TutorScreen } from "../src/TutorScreen.js";
import { DegradedNotices } from "../src/status/DegradedNotices.js";
import { LessonLinkProvider } from "../src/learn/link.js";
// Rendering one gallery state (DSN-15, DSN-16): the context (theme, motion, locale, text scale, elapsed time) wraps
// the component, which renders from the state's synthetic payload exactly as it renders live data.
import { useEffect, useMemo, useRef, type CSSProperties, type ReactNode } from "react";
import {
  EMPTY_KNOWS, EMPTY_LESSON, EMPTY_MOCKS, EMPTY_PRACTICE, ProfileController, StoreHolder, connectionKey, emptyConnection, emptyConnectivity, emptyStore, hydrate, knowsViewOf, optimistic,
  modelManagerView, readCheckResult, readHelp, readKnows, readLesson, readSubjectMap, reduce, reduceConnectivity, tutorSetup, type ConnectivitySlice, type Envelope,
  type CapturedQuestion, type CrashReport, type DueIdea, type KnowsView, type LessonPlayerView, type PartAnswer, type LicenceStatus, type MapView, type MemoryRec, type NoticeEntry,
  type PracticeView, type ProfilesView, type AssetEntry, type VoiceView, type ExamLock, type MockView, type TelemetrySummary,
  type PlanState, type ProgressState, type SearchState, followUps, type FollowUpKind, type GoalProgress, type AskView,
  type ExamCountdown, type ExamDatesView, type ExamReminder, type PastPaperSummary, type PastPapersView,
} from "@jana/client-core";
import type { Card, ModelCatalogue } from "@jana/contracts-ts";
import type { Locale } from "@jana/i18n";
import { ConnectivityIndicatorView } from "../src/connectivity/ConnectivityIndicator.js";
import { EgressNoticeView } from "../src/connectivity/EgressNotice.js";
import { LocaleProvider } from "../src/i18n.js";
import { Board, BoardStep } from "../src/board/Board.js";
import { EntryEditor } from "../src/composer/EntryEditor.js";
import type { JSONContent } from "@tiptap/core";
import { PhotoCapture, type CapturePreviewStage } from "../src/composer/PhotoCapture.js";
import { Composer } from "../src/composer/Composer.js";
import { LessonPlayerContent } from "../src/learn/LessonPlayer.js";
import { SubjectMapContent } from "../src/learn/SubjectMap.js";
import { KnowsContent } from "../src/memory/KnowsPage.js";
import { FirstRun } from "../src/setup/FirstRun.js";
import { FirstRunTutor } from "../src/setup/FirstRunTutor.js";
import { KnowsLinkProvider } from "../src/memory/link.js";
import { MemoryChipView } from "../src/memory/MemoryChip.js";
import { LaunchScreen } from "../src/primitives/BrandMark.js";
import { ModelManager } from "../src/settings/ModelManager.js";
import { RegistryProvider, Rendered, type Registry } from "../src/registry/registry.js";
import { ConnectionBanner } from "../src/status/StatusLine.js";
import { StoreProvider } from "../src/store.js";
import { CardView, defaultRegistry, type CardState } from "../src/transcript/parts.js";
import { Transcript, JumpToLatest } from "../src/transcript/Transcript.js";
import { VisualSettingsProvider } from "../src/visuals/VisualViewer.js";
import { Sidebar, StudioFrame, type SidebarContent } from "../src/frame/Frame.js";
import { KeyboardHelp } from "../src/frame/KeyboardHelp.js";
import { HintDock } from "../src/composer/HintDock.js";
import { PracticeContent } from "../src/learn/Practice.js";
import { AssessmentContent } from "../src/learn/Assessment.js";
import { SavedQuestionsContent } from "../src/learn/SavedQuestions.js";
import { StudyWorkspace } from "../src/learn/StudyWorkspace.js";
import { EMPTY_STUDY, type StudyWorkspaceController, type StudyWorkspaceView } from "@jana/client-core";
import { SessionNotesContent } from "../src/learn/SessionNotes.js";
import type { SessionNotesView } from "@jana/client-core";
import type { SavedQuestionsView } from "@jana/client-core";
import type { AssessmentView } from "@jana/client-core";
import { ProfilePickerView } from "../src/profiles/ProfilePicker.js";
import { ProfileRecoveryView, type RecoveryStep } from "../src/profiles/ProfileRecovery.js";
import { CalmScreen, type Helpline } from "../src/safety/CalmScreen.js";
import { AboutView, CrashReportView, LicenceView } from "../src/settings/Support.js";
import { OfflineHelpView, type HelpState } from "../src/settings/Help.js";
import { VoiceBarView } from "../src/voice/VoiceBar.js";
import { Home } from "../src/home/Home.js";
import { DailyGoalChip } from "../src/home/DailyGoal.js";
import { FollowUpChips, HelpChips } from "../src/chips/NextStepChips.js";
import { AskAnswer } from "../src/home/AskAnswer.js";
import { ExamLockNotice, MockContent, type MockActions, type MockSubject } from "../src/mock/MockExam.js";
import { ExamCountdownCard, ExamDatesPanel, PastPaperShelf, type PastPaperSubjectOption } from "../src/mock/PastPapers.js";
import { StudyAgreement } from "../src/settings/Studies.js";
import { ReportSchemaView } from "../src/settings/ReportSchema.js";
import { useT } from "../src/i18n.js";
import { PlanCard } from "../src/home/PlanCard.js";
import { ProgressContent } from "../src/progress/Progress.js";
import { SessionHistoryContent } from "../src/progress/SessionHistory.js";
import { AlertsContent, ParentSummaryContent } from "../src/settings/ParentSummary.js";
import type { HistoryView, ParentView } from "@jana/client-core";
import { SearchContent } from "../src/search/Search.js";
import { TutorLookProvider, TutorSection, tutorAvatarOf, tutorNameOf, useTutorAvatar, useTutorName } from "../src/settings/TutorSection.js";
import { Character, TutorPresence } from "../src/tutor/Character.js";
import { CHARACTER_POSES, type CharacterMouth, type CharacterPose, type VoiceStateName } from "../src/tutor/characters.js";
import { FirstRunTutorPick, type PickSeed } from "../src/tutor/TutorPick.js";

export interface GalleryState {
  id: string;
  title: string;
  note?: string;
  component: string;
  state: string;
  variant?: string;
  payload: Record<string, unknown>;
  payloadContract: string | null;
  context: { theme?: string; reducedMotion?: boolean; locale?: string; textScale?: number; elapsedMs?: number; [k: string]: unknown };
  placements: string[];
  expectText?: string[];
}

const SESSION = `ses_${"0".repeat(26)}`;
const EPOCH = "ep_gallery_state";

/** A store fed with the state's events, timed so the live clock reads `elapsedMs` (server time). */
function storeFor(state: GalleryState): StoreHolder {
  const holder = new StoreHolder();
  const now = Date.now();
  const at = now - (state.context.elapsedMs ?? 0);
  holder.update(() =>
    hydrate(emptyStore(), {
      session: { session_id: SESSION, title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false },
      cursor: { epoch: EPOCH, seq: 0 }, messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null,
    }),
  );
  const events = (state.payload.events as (Record<string, unknown> & { type: string })[] | undefined) ?? [];
  const turn = events.find((e) => e.type === "turn.start");
  const turnId = (turn?.turn_id as string | undefined) ?? null;
  holder.update((s) => {
    let next = s;
    const student = state.payload.student as string | undefined;
    const cli = "cli_" + "1".repeat(26);
    if (student !== undefined) next = optimistic(next, SESSION, cli, [{ type: "text", text: student }]);
    let seq = 0;
    const apply = (event: Record<string, unknown> & { type: string }) => {
      seq += 1;
      const envelope: Envelope = { v: 1, channel: "session", seq, epoch: EPOCH, session_id: SESSION, turn_id: event.type.startsWith("board.") ? null : turnId, ts: at, event };
      next = reduce(next, envelope);
    };
    for (const event of events) {
      if (event.type === "turn.start" && student !== undefined) {
        // The student's message belongs to this turn, as message.accepted says live (UIA-05).
        apply({ ...event, client_message_id: cli });
        apply({ type: "message.accepted", client_message_id: cli, message_id: event.user_message_id as string, turn_id: event.turn_id as string, disposition: "turn" });
        continue;
      }
      apply(event.type === "status" ? { ...event, phase_started_ts: at } : event);
    }
    const key = connectionKey(SESSION);
    const connectionState = (state.payload.state as never | undefined) ?? "live";
    next = { ...next, connection: { ...next.connection, [key]: { ...emptyConnection(), state: connectionState, banner: state.component === "ConnectionBanner", clock_offset_ms: 0, last_event_ts: at } } };
    return next;
  });
  return holder;
}

/** The reply a gallery board line was written in (a synthetic id). */
const GALLERY_TURN = `trn_${"4".repeat(26)}`;

const CARD_STATE: Record<string, CardState> = {
  canonical: "open", loading: "answering", slow: "answering", stalled: "answering", "error-retriable": "failed",
  "error-final": "expired", stopped: "cancelled", "reduced-motion": "open",
};

function AppStart({ failed }: { failed: boolean }) {
  return <LaunchScreen failed={failed} onRetry={() => undefined} />;
}

/** The connectivity slice from the state's `connectivity.status` and egress events, folded as the client folds them:
 * the status on the app channel, the events on the state's channel (a turn's on the session channel). */
function connectivityFor(state: GalleryState): ConnectivitySlice {
  const payload = state.payload as { status: Record<string, unknown> & { type: string }; events?: (Record<string, unknown> & { type: string })[]; channel?: "app" | "session" };
  const turn = `trn_${"3".repeat(26)}`;
  let seq = 0;
  const envelope = (event: Record<string, unknown> & { type: string }, channel: "app" | "session"): Envelope => {
    seq += 1;
    return { v: 1, channel, seq, epoch: EPOCH, session_id: channel === "session" ? SESSION : null, turn_id: channel === "session" ? turn : null, ts: Date.now(), event };
  };
  let slice = reduceConnectivity(emptyConnectivity(), envelope(payload.status, "app"));
  const channel = payload.channel ?? "session";
  if (channel === "session") slice = reduceConnectivity(slice, envelope({ type: "turn.start", turn_id: turn, user_message_id: null, client_message_id: null, intent: "ask", mode: "guided", fork: false }, "session"));
  for (const event of payload.events ?? []) slice = reduceConnectivity(slice, envelope(event, channel));
  return slice;
}

/** The knows page's view from the state's learner-view reply, checked and built as the controller does. */
function knowsView(state: GalleryState): KnowsView {
  if (state.state === "loading") return { ...EMPTY_KNOWS, status: "loading" };
  if (state.state === "error-retriable") return { ...EMPTY_KNOWS, status: "failed" };
  return knowsViewOf(readKnows((state.payload as { knows: unknown }).knows));
}

/** The subject map's view from the state's map reply, checked as the controller checks it. */
function mapView(state: GalleryState): MapView {
  const payload = state.payload as { map?: unknown; subject_id?: string; syllabus?: string };
  if (state.state === "loading") return { status: "loading", subjectId: payload.subject_id ?? null, map: null };
  if (state.state === "error-retriable") return { status: "failed", subjectId: payload.subject_id ?? null, map: null };
  const map = readSubjectMap(payload.map);
  return { status: "ready", subjectId: map.subject_id, map, syllabus: payload.syllabus ?? null };
}

/** The lesson player's view from the state's lesson reply and marked checks, checked as the controller checks them. */
function lessonView(state: GalleryState): LessonPlayerView {
  const payload = state.payload as { lesson?: unknown; lesson_id?: string; index?: number; checks?: Record<string, unknown>; tries?: Record<string, number>; answers?: Record<string, PartAnswer[]>; positionFailed?: boolean };
  if (state.state === "loading") return { ...EMPTY_LESSON, status: "loading", lessonId: payload.lesson_id ?? null };
  if (state.state === "error-retriable") return { ...EMPTY_LESSON, status: "failed", lessonId: payload.lesson_id ?? null };
  const lesson = readLesson(payload.lesson);
  const checks = Object.fromEntries(Object.entries(payload.checks ?? {}).map(([id, result]) => [id, { status: "marked" as const, result: readCheckResult(result), tries: payload.tries?.[id] ?? 1, answers: payload.answers?.[id] ?? [] }]));
  return { ...EMPTY_LESSON, status: "ready", lessonId: lesson.lesson_id, lesson, index: payload.index ?? 0, checks, positionFailed: payload.positionFailed === true };
}

/** The left rail (the sidebar, DSN-25's LeftRail placement) from data: the places by their catalogue keys, the recent
 * sessions and the student, in the variant the state names. */
function LeftRail({ state, framed = false }: { state: GalleryState; framed?: boolean }) {
  const t = useT();
  const payload = state.payload as { variant: "full" | "rail"; places: { id: string; icon: string; labelKey: string; current: boolean }[];
    sessions: SidebarContent["sessions"]; profile: { name: string; disc: number; detail?: string }; menuOpen?: boolean; online?: boolean };
  const noop = () => undefined;
  const content: SidebarContent = {
    places: payload.places.map((p) => ({ id: p.id, icon: p.icon as never, label: t(p.labelKey), current: p.current, onSelect: noop })),
    onNewQuestion: noop, sessions: payload.sessions, onOpenSession: noop, profile: payload.profile,
    onSwitch: noop, onSettings: noop, settingsCurrent: false,
    menu: { onLanguage: noop, onHelp: noop, onKeys: noop, onBackup: noop, plan: { label: t(payload.online === true ? "frame.menu.plan_online" : "frame.menu.plan_free"), onOpen: noop } },
  };
  // A state with the student menu open opens it the way a student does, from its row.
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => { if (payload.menuOpen === true) root.current?.querySelector<HTMLElement>("[data-student-menu]")?.click(); }, [payload.menuOpen]);
  if (framed) return <div className="h-160"><StudioFrame sidebar={(props) => <Sidebar {...props} content={content} />}><TutorScreen sessionId={SESSION} /></StudioFrame></div>;
  return <div ref={root} className="flex h-160"><Sidebar variant={payload.variant} onToggle={noop} onDone={noop} content={content} /></div>;
}

/** Practice's view from the state: the question and its tries as the core marked them. */
function practiceView(state: GalleryState): PracticeView {
  const payload = state.payload as Partial<PracticeView>;
  const status = ({ loading: "starting", empty: "done", "error-retriable": "failed", "error-final": "unavailable" } as Record<string, PracticeView["status"]>)[state.state] ?? "ready";
  return { ...EMPTY_PRACTICE, ...payload, status };
}

const NO_MOCK_ACTIONS: MockActions = {
  onChoose: () => undefined, onOpen: () => undefined, onStart: () => undefined, onPause: () => undefined, onResume: () => undefined, onShow: () => undefined,
  onAnswer: () => undefined, onFlag: () => undefined, onClear: () => undefined, onSubmit: () => undefined, onRetryMark: () => undefined, onRetry: () => undefined,
  onRetrySave: () => undefined,
  onLeave: () => undefined, onShowWhy: () => undefined, onPractise: () => undefined, onPractiseTopic: () => undefined,
};

/** A mock exam screen from its state (UXS-25, UXS-26): the view as the controller holds it, read at time 0 and shown at
 * time 0, so the clock reads exactly the sitting's `remaining_ms`. */
function MockState({ state }: { state: GalleryState }) {
  const payload = state.payload as { view: Partial<MockView>; subjects: MockSubject[]; names: { topics: Record<string, string>; kcs: Record<string, string> }; extraPercent?: number; pastPapers?: PastPaperSummary[] };
  const view: MockView = { ...EMPTY_MOCKS, status: "ready", ...payload.view, readAt: 0, listedAt: 0 };
  const names = { topic: (id: string) => payload.names.topics[id] ?? id, kc: (id: string) => payload.names.kcs[id] ?? id };
  return <MockContent view={view} now={0} actions={NO_MOCK_ACTIONS} subjects={payload.subjects} extraPercent={payload.extraPercent ?? 0} names={names} pastPapers={payload.pastPapers ?? []} />;
}

/** A profile controller for gallery states that render a pick: nothing is saved from the gallery. */
function galleryProfiles(): ProfileController {
  return new ProfileController({ endpoint: async () => ({ baseUrl: "http://gallery.test", token: "gallery" }) }, new StoreHolder());
}

/** Data-only study fixtures use the same view; no provider or profile endpoint is involved. */
function StudyFixture({ state }: { state: GalleryState }) {
  const t = useT(), root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (state.variant === "sets") Array.from(root.current?.querySelectorAll("button") ?? [])
      .find((button) => button.textContent?.trim() === t("study.all_sets"))?.click();
  }, [state.variant, t]);
  const controller = useMemo(() => {
    const view = { ...EMPTY_STUDY, ...(state.payload.view as Partial<StudyWorkspaceView>) } as StudyWorkspaceView;
    const noop = async () => undefined;
    return { getView: () => view, subscribe: () => () => undefined, load: noop, close: () => undefined,
      open: noop, refreshOpened: noop, upload: noop, generate: noop, addText: noop, jobAction: noop,
      showAid: noop, rate: noop, submit: noop, correctText: noop, markPrivate: noop, remove: noop,
      startExtraction: noop, selectExtra: noop, loadNotes: noop, importNote: noop, loadTopics: noop,
      playOverview: noop, stopReading: () => undefined, saveDraft: noop, loadMaterialTopics: noop, openSet: noop,
      hideAid: () => undefined, clearResult: () => undefined, loadMedia: async () => null, seek: () => undefined,
      readCitation: async () => true } as unknown as StudyWorkspaceController;
  }, [state]);
  return <div ref={root} className="contents"><StudyWorkspace controller={controller} /></div>;
}

/** The label a tutor turn carries: the still character and the tutor's name (D105). */
function TutorTurnLabel() {
  const avatar = useTutorAvatar();
  const name = useTutorName();
  return <p className="flex items-center gap-2 text-label text-tutor"><Character id={avatar} size={16} animate={false} /><span data-tutor-name="">{name}</span></p>;
}

function Component({ state }: { state: GalleryState }): ReactNode {
  const t = useT();
  switch (state.component) {
    case "Settings": return <SettingsPreview state={state.state} />;
    case "AppShell": return <LeftRail state={state} framed />;
    case "QuestionDock": return <QuestionDock sessionId={SESSION} />;
    case "YourTurnLine": return <WorkingEntry sessionId={SESSION} />;
    case "MathInput": return <EntryEditor label={t("composer.label")} placeholder="" initialDocument={state.payload.document as JSONContent} onSubmit={() => false} />;
    case "JumpToLatest": return <div className="relative min-h-24"><JumpToLatest onClick={() => undefined} /></div>;
    case "CardGallery": return <div className="flex flex-col gap-4">{(state.payload.cards as Card[]).map((card, i) => <CardView key={i} card={card} state="open" onAnswer={() => undefined} />)}</div>;
    case "TutorScreen":
      // Standalone tutor fixtures need the same responsive frame context as the shipping app.
      return <LeftRail state={tutorFrame as GalleryState} framed />;
    case "DegradedNotices":
      return <DegradedNotices {...(state.payload as unknown as Parameters<typeof DegradedNotices>[0])} onOpenLessons={() => undefined} onOnlineFeatures={() => undefined} />;
    case "TutorTurn":
      return <Transcript sessionId={SESSION} />;
    case "QuestionCard":
    case "HintCard":
    case "PlanCard":
    case "ReflectionCard":
    case "ConfirmCard":
      return <CardView card={state.payload as unknown as Card} state={CARD_STATE[state.state] ?? "open"} elapsedMs={state.context.elapsedMs ?? 0} onAnswer={() => undefined} onRetry={() => undefined} />;
    case "BoardStep": {
      const step = state.payload as unknown as Parameters<typeof BoardStep>[0]["step"] & { index: number };
      // A tutor line carries its line menu with "Report a problem" (UXS-44), naming the reply that wrote it.
      return <ol>{<BoardStep step={step} number={step.index + 1} current={step.status === "awaiting"} sessionId={SESSION} reportTurn={GALLERY_TURN} />}</ol>;
    }
    case "Board":
      return <Board sessionId={SESSION} />;
    case "FunctionGraph":
      return <Rendered keys={["visual:function_graph", "visual:*"]} data={state.payload} lifecycle={state.state === "error-final" ? "fallback" : "complete"} partId="gallery" />;
    case "VisualViewer":
      return (
        <VisualSettingsProvider settings={{ reducedMotion: state.context.reducedMotion === true, textScale: state.context.textScale ?? 1 }}>
          <Rendered keys={[`visual:${String(state.payload.type)}`, "visual:*"]} data={state.payload} lifecycle="complete" partId="gallery" />
        </VisualSettingsProvider>
      );
    case "ConnectionBanner":
      return <ConnectionBanner sessionId={SESSION} />;
    case "AccountingEntry":
      return <EntryEditor key={state.id} label={state.title} placeholder="" accounting initialDocument={state.payload.document as JSONContent} onSubmit={() => false} />;
    case "PhotoCapture":
      return <PhotoCapture previewProcessingElapsed={["reading", "preprocessing"].includes(String(state.payload.status))} previewStage={state.variant as CapturePreviewStage} key={state.id} sessionId={SESSION} purpose="question" previewCapture={state.payload as unknown as CapturedQuestion} {...(state.variant?.startsWith("camera-") || state.payload.status === "refused" || state.payload.status === "cancelled" ? {} : { previewImage: new URL("./assets/capture-sheet.svg", import.meta.url).href })} onConfirmed={() => undefined} onTyped={() => undefined} onClose={() => undefined} />;
    case "Composer":
      return <Composer sessionId={SESSION} />;
    case "Transcript":
      return <Transcript sessionId={SESSION} />;
    case "AppStart":
      return <AppStart failed={state.state === "error-final"} />;
    case "KnowsPage":
      return (
        <KnowsContent view={knowsView(state)} onForget={() => undefined} onResolve={() => undefined} onDisputeMistake={() => undefined} onSetPreference={() => undefined}
          onRetry={() => undefined} onOpenSettings={() => undefined} onClose={() => undefined} />
      );
    case "SubjectMap": {
      const open = (state.payload as { open?: string }).open;
      const actions = { onStartLesson: () => undefined, onPractise: () => undefined, onAsk: () => undefined, onMasteryCheck: () => undefined };
      return <SubjectMapContent view={mapView(state)} onRetry={() => undefined} actions={actions} {...(open !== undefined ? { initialTopic: open } : {})} />;
    }
    case "LessonPlayer": {
      // On the content-only class no tutor answers, so "Ask about this" is not offered (PLT-29).
      const tutor = state.context.hardwareClass !== "content-only";
      return (
        <LessonPlayerContent view={lessonView(state)}
          actions={{ onGo: () => undefined, onAnswer: () => undefined, onClose: () => undefined, onRetry: () => undefined, ...(tutor ? { onAsk: () => undefined } : {}) }} />
      );
    }
    case "FirstRunTutor": {
      const setup = state.state === "loading" ? tutorSetup(null) : tutorSetup(state.payload as unknown as ModelCatalogue);
      return <FirstRunTutor name={String(state.context.studentName ?? "Ada")} setup={setup} elapsedMs={state.context.elapsedMs ?? 0} onContinue={() => undefined} onOnlineFeatures={() => undefined} />;
    }
    case "FirstRun": {
      // "Who's learning?" (UXS-10 step 1): nothing is sent from the gallery, so the controller never reaches a core.
      const profiles = new ProfileController({ endpoint: async () => ({ baseUrl: "http://gallery.test", token: "gallery" }) }, new StoreHolder());
      return <FirstRun profiles={profiles} packs={[]} onStarted={() => undefined} />;
    }
    case "ModelManager": {
      // Settings → Tutor models (UXS-11) from a model catalogue; with every online feature off (the default) downloads
      // are off too.
      const catalogue = state.state === "loading" ? null : (state.payload as unknown as ModelCatalogue);
      const view = modelManagerView(catalogue, { downloadsOn: (state.context.connectivity ?? "all-off") !== "all-off" });
      const noop = () => undefined;
      return <ModelManager view={view} actions={{ onDownload: noop, onPause: noop, onResume: noop, onDelete: noop, onImport: noop, onFreeSpace: noop, onOnlineFeatures: noop }} />;
    }
    case "ConnectivityIndicator":
      return (
        <div className="relative flex min-h-40 flex-col justify-end">
          <ConnectivityIndicatorView slice={connectivityFor(state)} open={state.payload.open === true} onToggle={() => undefined} onSendNow={() => undefined} onOpenLedger={() => undefined} />
        </div>
      );
    case "EgressNotice": {
      const notice = state.payload as { path: string; destination_label: string };
      return <EgressNoticeView path={notice.path} destination={notice.destination_label} />;
    }
    case "MemoryChip": {
      const saved = state.payload as { note_id: string; text: string; undo_until_ts: number };
      const memory: MemoryRec = { note_id: saved.note_id, session_id: SESSION, turn_id: null, text: saved.text, undo_until_ts: saved.undo_until_ts, state: state.variant === "forgotten" ? "forgotten" : "saved", seq: 1 };
      const undo = state.state === "loading" ? "undoing" : state.state === "error-retriable" ? "failed" : "idle";
      return <MemoryChipView memory={memory} undoLeftMs={state.variant === "expired" ? 0 : 30_000} state={undo} onUndo={() => undefined} onOpen={() => undefined} />;
    }
    case "LeftRail":
      return <LeftRail state={state} />;
    case "Practice":
      return <PracticeContent view={practiceView(state)} subjectLabel={String(state.payload.subjectLabel ?? "")}
        actions={{ onAnswer: () => undefined, onNext: () => undefined, onEnd: () => undefined, onHelp: () => undefined, onDontKnow: () => undefined, onLearn: () => undefined, onMixed: () => undefined, onRetry: () => undefined }} />;
    case "Assessment": {
      const noop = () => undefined;
      return <AssessmentContent view={state.payload.view as unknown as AssessmentView} subjects={["physics", "chemistry"]}
        names={{ subject: (s) => t(`settings.profiles.subject.${s}`), topic: () => "Motion", kc: () => "Speed" }}
        actions={{ onStart: noop, onOpen: noop, onAnswer: noop, onStop: noop, onResume: noop, onRefresh: noop, onRetry: noop, onList: noop, onClose: noop }} />;
    }
    case "SavedQuestions": {
      const noop = () => undefined;
      return <SavedQuestionsContent view={state.payload.view as unknown as SavedQuestionsView}
        subject={(s) => t(`settings.profiles.subject.${s}`)} topic={() => "Motion"}
        actions={{ onSelect: noop, onStatus: noop, onRemove: noop, onRetry: noop, onClose: noop, onPrint: noop }} />;
    }
    case "StudyWorkspace": return <StudyFixture state={state} />;
    case "SessionNotes": {
      const noop = () => undefined;
      if (state.state === "locked") return <ExamLockNotice lock={state.payload.lock as unknown as ExamLock} now={0} place="notes" onOpen={noop} />;
      return <SessionNotesContent view={state.payload.view as unknown as SessionNotesView} subject={(s) => t(`settings.profiles.subject.${s}`)} kc={() => "Average speed"}
        topicForKc={(id) => id === "kc.phy.o.motion.average_speed" ? { id: "cur.phy.o.motion", title: "Motion" } : null}
        actions={{ onSearch: noop, onOpen: noop, onClose: noop, onRetry: noop, onPrivate: noop, onDelete: noop, onReference: async () => true, onExport: noop }} />;
    }
    case "ProfilePicker": {
      const status = state.state === "loading" ? "loading" : state.state === "error-final" ? "failed" : "ready";
      const view = { status, profiles: (state.payload.profiles as ProfilesView["profiles"] | undefined) ?? [], active: null, settings: null, opening: {}, ended: null } as unknown as ProfilesView;
      return <ProfilePickerView view={view} chosen={null} onOpen={() => undefined} onRecovery={() => undefined} />;
    }
    case "ProfileRecovery": {
      const step = ({ loading: "restoring", "error-retriable": "failed" } as Record<string, RecoveryStep>)[state.state] ?? (state.variant === "done" ? "done" : "choose");
      return <ProfileRecoveryView mode={state.variant === "restore" ? "restore" : "recover"} step={step} file={null} onRetry={() => undefined} onRestore={() => undefined} onChoose={() => undefined} onPassphrase={() => undefined} onBack={() => undefined} />;
    }
    case "KeyboardHelp":
      return <KeyboardHelp open characterKeys={state.variant !== "character-off"} onClose={() => undefined} />;
    case "CalmScreen":
      return <div className="h-160"><CalmScreen text={String(state.payload.text)} helplines={(state.payload.helplines as Helpline[] | undefined) ?? []} onBack={() => undefined} /></div>;
    case "Licence":
      return <LicenceView status={state.state === "error-retriable" ? "failed" : state.state === "loading" ? "loading" : (state.payload as unknown as LicenceStatus)} />;
    case "CrashReport": {
      const report = (state.payload as { reports: CrashReport[] }).reports[0];
      return report === undefined ? null : <ul><CrashReportView report={report} onDecide={() => undefined} /></ul>;
    }
    case "SettingsAbout": {
      const payload = state.payload as { version: string; notices: NoticeEntry[]; assets: AssetEntry[] };
      return <AboutView version={payload.version} notices={payload.notices} assets={payload.assets} />;
    }
    case "SettingsHelp": {
      // Settings → Help's offline help (OPS-23): the core's reply as the client checks it, or the state it stands for.
      const payload = state.payload as { reply?: unknown; query?: string; open?: string };
      const help: HelpState = state.state === "loading" ? "loading" : state.state === "error-retriable" ? "failed" : state.state === "error-final" ? null : readHelp(payload.reply);
      return <OfflineHelpView state={help} query={payload.query ?? ""} open={payload.open ?? null} onQuery={() => undefined} onToggle={() => undefined} onOpenArticle={() => undefined} onRetry={() => undefined} />;
    }
    case "HintDock":
      return <HintDock sessionId={SESSION} onSolution={() => undefined} />;
    case "MockSitting":
    case "MockPapers":
      return <MockState state={state} />;
    case "PastPapers": {
      // Imported past papers in the Mock exam place (ASM-27): the list, an import's questions and a refusal.
      const payload = state.payload as { view: PastPapersView; subjects: PastPaperSubjectOption[] };
      const noop = () => undefined;
      return <PastPaperShelf view={payload.view} subjects={payload.subjects} locked={false} actions={{ onImport: noop, onSit: noop, onRemove: noop, onDismiss: noop, onRetry: noop }} />;
    }
    case "ExamDates": {
      // Exam dates and their reminders switch (LRN-44).
      const payload = state.payload as { view: ExamDatesView; subjects: PastPaperSubjectOption[] };
      const noop = () => undefined;
      return <ExamDatesPanel view={payload.view} subjects={payload.subjects} actions={{ onAdd: noop, onReminders: noop, onRemove: noop }} />;
    }
    case "ExamCountdown": {
      // Home's countdown to the nearest exam and a reminder due (LRN-44).
      const payload = state.payload as { countdown: ExamCountdown | null; reminders: ExamReminder[] };
      return <ExamCountdownCard countdown={payload.countdown} reminders={payload.reminders} onDismiss={() => undefined} onOpen={() => undefined} />;
    }
    case "ExamLock": {
      const payload = state.payload as { lock: ExamLock; place: "tutor" | "lessons" };
      return <ExamLockNotice lock={payload.lock} now={0} place={payload.place} onOpen={() => undefined} />;
    }
    case "StudyAgreement":
      return <StudyAgreement scope={String(state.payload.scope)} adult={state.payload.adult === true} open busy={false} refused={null} onCancel={() => undefined} onAgree={() => undefined} />;
    case "ReportSchema":
      return <ReportSchemaView summary={state.payload.summary as TelemetrySummary} />;
    case "VoiceBar": {
      const view = state.payload as unknown as VoiceView;
      const noop = () => undefined;
      return <VoiceBarView view={view} starting={state.state === "loading"} restart={state.variant === "gave-up"}
        actions={{ onToggle: noop, onConversation: noop, onRestart: noop, onMode: noop, onHold: noop, onStop: noop }} />;
    }
    case "HomePlan": {
      // Home's study plan (UXS-12): the plan card in a state, with the topic names and started ideas it reads.
      const payload = state.payload as { plan: PlanState; streak: { days: number; freezes: number } | null; topics: Record<string, string>; started: string[] };
      const noop = () => undefined;
      return (
        <PlanCard state={payload.plan} streak={payload.streak} names={{ topic: (kc) => payload.topics[kc] ?? null, started: (kc) => payload.started.includes(kc) }}
          actions={{ onStart: noop, onChange: noop, onNotToday: noop, onContinue: noop, onKeepLearning: noop, onAnother: noop, onRetry: noop }} />
      );
    }
    case "Progress": {
      // Progress (UXS-27): the screen from a progress view, with the idea statements the subject maps give.
      const payload = state.payload as { progress: ProgressState["progress"]; kcNames?: Record<string, string> };
      const status: ProgressState["status"] = state.state === "loading" ? "loading" : state.state === "error-retriable" ? "failed" : state.state === "error-final" ? "unavailable" : "ready";
      return <ProgressContent state={{ status, progress: status === "ready" || status === "loading" ? payload.progress : null }}
        names={{ subject: (s) => t(`settings.profiles.subject.${s}`), kc: (kc) => payload.kcNames?.[kc] ?? null }} actions={{ onRetry: () => undefined, onKnows: () => undefined, onNotes: () => undefined, onLearn: () => undefined }} />;
    }
    case "ParentSummary":
    case "PrintedReport": {
      // Settings → Parent summary (UXS-33, TCH-12) from a digest, and the same summary as it prints (DSN-22): the report
      // header with the product's name and the date generated.
      const payload = state.payload as { view: Pick<ParentView, "digestStatus" | "digest">; name: string };
      return <ParentSummaryContent view={payload.view} name={payload.name} printing={state.component === "PrintedReport"} onRetry={() => undefined} onPrint={() => undefined} />;
    }
    case "Alerts": {
      // Settings → Alerts (TCH-14, TABLE UXS-46a): kind and date only, newest first.
      const payload = state.payload as { view: Pick<ParentView, "alertsStatus" | "alerts" | "dismissing" | "dismissFailed">; ideas?: Record<string, string> };
      return <AlertsContent view={payload.view} idea={(kc) => payload.ideas?.[kc] ?? null} onDismiss={() => undefined} onRetry={() => undefined} />;
    }
    case "SessionHistory": {
      // Progress → Session history (UXS-48): the list, one session read-only, a purged one and a mock's lock.
      const noop = () => undefined;
      return <SessionHistoryContent view={state.payload.view as unknown as HistoryView} subject={(s) => t(`settings.profiles.subject.${s}`)}
        actions={{ onOpen: noop, onBack: noop, onClose: noop, onRetry: noop, onMore: noop }} />;
    }
    case "WorkedSearch": {
      // Worked-solution search (UXS-51): the search screen in a state, with topic names by idea.
      const payload = state.payload as { search: SearchState; topics: Record<string, string> };
      const noop = () => undefined;
      return <SearchContent state={payload.search} names={{ topic: (kc) => payload.topics[kc] ?? null, subject: () => "physics" }}
        actions={{ onSearch: noop, onOpen: noop, onClose: noop, onSolution: noop, onBrowse: noop, onPractise: noop }} />;
    }
    case "SettingsTutor": {
      // Settings → Tutor's one pick (UXS-54, PRM-03, D103): the tutor's character and name from the profile's settings,
      // a draft and its error where the state has one, and the label the choice puts on the tutor's turns (D105).
      const settings = state.payload.settings as Parameters<typeof TutorSection>[0]["settings"];
      const seed = state.payload.seed as PickSeed | undefined;
      return (
        <TutorLookProvider avatar={tutorAvatarOf(settings)} name={tutorNameOf(settings)}>
          <TutorSection profiles={galleryProfiles()} settings={settings} {...(seed !== undefined ? { seed } : {})} />
          <TutorTurnLabel />
        </TutorLookProvider>
      );
    }
    case "FirstRunTutorPick": {
      // The first-session interview's opening pick (UXS-10 step 2, UXS-54), skippable with "Keep Jana".
      const settings = state.payload.settings as Parameters<typeof TutorSection>[0]["settings"];
      return <FirstRunTutorPick profiles={galleryProfiles()} settings={settings} onDone={() => undefined} />;
    }
    case "TutorCharacter": {
      // One character in one pose of TABLE DSN-26b (with a speaking mouth shape), or every pose side by side.
      const payload = state.payload as { character: string; pose?: CharacterPose; mouth?: CharacterMouth; sheet?: boolean };
      if (payload.sheet === true) {
        return (
          <div className="flex flex-wrap items-end gap-4">
            {CHARACTER_POSES.map((pose) => <Character key={pose} id={payload.character} pose={pose} size={96} />)}
          </div>
        );
      }
      return <Character id={payload.character} pose={payload.pose ?? "idle"} size={160} {...(payload.mouth !== undefined ? { mouth: payload.mouth } : {})} />;
    }
    case "TutorPresence": {
      // The presence (UXS-53): the character in a voice state's pose with the state's words beside it (VOC-17).
      const payload = state.payload as { character: string; state: VoiceStateName; pointing?: boolean };
      return <TutorPresence id={payload.character} state={payload.state} size={72} pointing={payload.pointing === true} />;
    }
    case "AskAnswer": {
      // Ask anything's answer under Home's box (STU-20): searching, answered (Teach me, or Just explain at 18 or over)
      // with citations and the general-knowledge label, and the offline message with its two ways on.
      const noop = () => undefined;
      return <AskAnswer view={state.payload as unknown as AskView} actions={{ onTutor: noop, onStudy: noop, onExplain: noop, onAgain: noop }} />;
    }
    case "Home": {
      const payload = state.payload as { name: string; pickup: { sessionId: string; title: string; subject: string; subjectLabel: string; day: "today" | "yesterday" | "week" | "older" }[]; ideas: DueIdea[]; goal?: GoalProgress };
      return (
        <Home {...(payload.goal !== undefined ? { goal: <DailyGoalChip progress={payload.goal} onChange={() => undefined} /> } : {})} name={payload.name} ask={<Composer sessionId={SESSION} asking placement="inline" />} subjects={[]} onSubject={() => undefined}
          materials={{ onUpload: () => undefined, onLink: () => undefined, onPaste: () => undefined, onRecord: () => undefined }}
          pickup={payload.pickup} onPickup={() => undefined} practice={{ ideas: payload.ideas, refreshes: payload.ideas.filter((i) => i.kc.state === "needs_review").length, subjectLabel: (s) => s }}
          onPractice={() => undefined} />
      );
    }
    case "NextStepChips": {
      // Help before the answer and the next step after it (D120): the help chips (ASM-28) and at most two follow-ups
      // after a reply (UXS-68), as the catalogue words them.
      const payload = state.payload as { followUps: FollowUpKind[] };
      return (
        <div className="flex flex-col gap-4">
          <HelpChips onHelp={() => undefined} hintKeys="Alt+H" />
          <FollowUpChips chips={followUps(payload.followUps, (kind) => t(`followup.${kind}`))} onChoose={() => undefined} />
        </div>
      );
    }
    default:
      return null;
  }
}

export function GalleryView({ state, registry }: { state: GalleryState; registry?: Registry }) {
  const holder = useMemo(() => {
    if (state.component === "Composer") {
      const h = storeFor({ ...state, payload: {} });
      const turns = Number(state.payload.turns ?? 0);
      if (turns > 0) {
        const live = state.payload.live === true;
        h.update((s) => reduce(s, { v: 1, channel: "session", seq: 1, epoch: EPOCH, session_id: SESSION, turn_id: `trn_${"2".repeat(26)}`, ts: Date.now(), event: { type: "turn.start", turn_id: `trn_${"2".repeat(26)}`, user_message_id: null, client_message_id: null, intent: "ask", mode: "guided", fork: false } }));
        if (!live) h.update((s) => reduce(s, { v: 1, channel: "session", seq: 2, epoch: EPOCH, session_id: SESSION, turn_id: `trn_${"2".repeat(26)}`, ts: Date.now(), event: { type: "turn.end", status: "complete", stop_reason: "completed", elapsed_ms: 1000, usage: null, verification: "not_applicable", persisted: { message_id: `msg_${"2".repeat(26)}`, part_ids: [] }, degraded: false, degraded_reason: null } }));
      }
      return h;
    }
    const h = storeFor(state);
    if (state.component === "QuestionDock" && state.state === "loading") h.update((s) => ({ ...s, requests: Object.fromEntries(Object.entries(s.requests).map(([id, r]) => [id, { ...r, state: "answering" as const }])) }));
    return h;
  }, [state]);
  const locale = (state.context.locale ?? "en") as Locale;
  // A state may start with a field focused (`payload.focusField`, a selector inside the fixture): the focus look.
  const fixture = useRef<HTMLDivElement>(null);
  const focus = typeof state.payload.focusField === "string" ? state.payload.focusField : null;
  useEffect(() => { if (focus !== null) requestAnimationFrame(() => fixture.current?.querySelector<HTMLElement>(focus)?.focus()); }, [focus]);
  return (
    <div
      ref={fixture}
      data-gallery-id={state.id}
      data-theme={state.context.theme ?? "light"}
      data-reduced-motion={state.context.reducedMotion === true ? "true" : undefined}
      style={{ "--text-scale": state.context.textScale ?? 1, fontSize: "calc(var(--text-body) * var(--text-scale))" } as CSSProperties}
      className="bg-paper p-4 text-ink"
    >
      <LocaleProvider locale={locale}>
        <RegistryProvider registry={registry ?? defaultRegistry()}>
          <StoreProvider holder={holder} session={null}>
            <KnowsLinkProvider open={() => undefined}>
              <LessonLinkProvider open={() => undefined} openTopic={() => undefined}><Component state={state} /></LessonLinkProvider>
            </KnowsLinkProvider>
          </StoreProvider>
        </RegistryProvider>
      </LocaleProvider>
    </div>
  );
}
