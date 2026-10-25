// The gallery index (DSN-15, UXS-02, UXS-36): every component declares the states it renders, and every declared
// state has at least one data-only fixture in `states/`.
import type { GalleryState } from "./GalleryView.js";

const files = import.meta.glob<GalleryState>("./states/*.json", { eager: true, import: "default" });

export const STATES: GalleryState[] = Object.values(files).sort((a, b) => a.id.localeCompare(b.id));

const CARD_STATES = ["canonical", "loading", "slow", "stalled", "error-retriable", "error-final", "stopped", "reduced-motion"];

export const DECLARED: Record<string, string[]> = {
  Settings: ["canonical", "loading", "error-retriable"],
  AppShell: ["canonical"],
  QuestionDock: ["canonical", "loading"],
  YourTurnLine: ["canonical"],
  MathInput: ["canonical"],
  JumpToLatest: ["canonical"],
  CardGallery: ["canonical"],
  TutorScreen: ["canonical"],
  DegradedNotices: ["canonical"],
  TutorTurn: ["canonical", "loading", "model-loading", "slow", "stalled", "long-stalled", "error-retriable", "error-final", "stopped", "reduced-motion"],
  QuestionCard: CARD_STATES,
  HintCard: CARD_STATES,
  PlanCard: CARD_STATES,
  ReflectionCard: CARD_STATES,
  ConfirmCard: CARD_STATES,
  BoardStep: ["canonical", "loading", "reduced-motion"],
  Board: ["canonical", "empty", "reduced-motion"],
  FunctionGraph: ["canonical", "error-final", "reduced-motion"],
  VisualViewer: ["canonical", "error-final", "reduced-motion"],
  ConnectionBanner: ["canonical", "loading"],
  AccountingEntry: ["canonical", "error-retriable"],
  PhotoCapture: ["canonical", "loading", "error-retriable", "error-final", "stopped"],
  Composer: ["canonical", "empty", "loading"],
  Transcript: ["canonical", "empty"],
  AppStart: ["loading", "error-final"],
  KnowsPage: ["canonical", "empty", "loading", "error-retriable"],
  MemoryChip: ["canonical", "loading", "error-retriable"],
  SubjectMap: ["canonical", "loading", "empty", "error-retriable", "error-final"],
  LessonPlayer: ["canonical", "loading", "error-retriable"],
  // First run (UXS-10): "Who's learning?" and the student hand-off after it.
  FirstRun: ["canonical"],
  FirstRunTutor: ["canonical", "loading"],
  // Every S2 state of TABLE UXS-06a (UXS-06, DSN-19); the queue of UXS-08.
  ConnectivityIndicator: ["canonical", "offline", "online-unavailable", "queued", "reduced-motion"],
  // The pre-send notice of each DAT-18 egress path and the LAN compute server (PRV-28).
  EgressNotice: ["canonical"],
  // Settings → Tutor models (UXS-11): the states it names, as UXS-02 states with variants.
  ModelManager: ["canonical", "loading", "queued", "error-retriable", "error-final"],
  // Stage 3 (direction A): the sidebar as the left rail (DSN-25's LeftRail placement), Home, Practice (UXS-24), the
  // profile picker (UXS-09) and recovery (UXS-47), the keyboard help (LOC-12), the calm screen (UXS-43), Settings →
  // Licence, crash reports and About (PLT-19, OBS-17, PLT-10), the hint dock (UXS-17) and the voice bar (UXS-34).
  LeftRail: ["canonical"],
  Home: ["canonical", "empty"],
  // Ask anything under Home's box (STU-20, UXS-67): answered, searching, offline and could not answer.
  AskAnswer: ["canonical", "loading", "offline", "error-retriable"],
  Practice: ["canonical", "loading", "empty", "error-retriable", "error-final"],
  Assessment: ["canonical", "loading", "error-retriable", "error-final"],
  SavedQuestions: ["canonical", "loading", "empty", "error-retriable", "error-final"],
  StudyWorkspace: ["canonical", "loading", "empty", "error-retriable"],
  SessionNotes: ["canonical", "loading", "empty", "model-loading", "error-retriable", "error-final", "offline", "locked"],
  ProfilePicker: ["canonical", "empty", "loading", "error-final"],
  ProfileRecovery: ["canonical", "loading", "error-retriable"],
  KeyboardHelp: ["canonical"],
  CalmScreen: ["canonical", "empty"],
  Licence: ["canonical", "error-retriable"],
  CrashReport: ["canonical"],
  SettingsAbout: ["canonical"],
  SettingsHelp: ["canonical", "loading", "empty", "error-retriable", "error-final"],
  HintDock: ["canonical"],
  VoiceBar: ["canonical", "loading", "error-retriable", "error-final"],
  // Stage 4b: the mock sitting in each `sitting.state` of TABLE UXS-25a and its report (UXS-25, UXS-26), the Mock exam
  // place (papers and the student's mocks), the lock a place shows during a sitting (AGT-24), a research study's
  // agreement (PRV-06, D87) and what a usage report holds (OBS-20).
  MockSitting: ["canonical", "loading", "error-retriable"],
  MockPapers: ["canonical", "loading", "empty", "error-retriable", "error-final"],
  ExamLock: ["locked"],
  StudyAgreement: ["canonical"],
  ReportSchema: ["canonical"],
  // Stage 5: Home's study plan (UXS-12; proposed, changing, started, finished, set aside), Progress (UXS-27),
  // worked-solution search (UXS-51) and Settings → Tutor (PRM-03).
  HomePlan: ["canonical", "loading", "empty", "error-retriable"],
  // M45.c: imported past papers in the Mock exam place (ASM-27), exam dates and Home's countdown (LRN-44).
  PastPapers: ["canonical", "loading", "empty", "error-retriable"],
  ExamDates: ["canonical", "empty"],
  ExamCountdown: ["canonical"],
  Progress: ["canonical", "loading", "empty", "error-retriable", "error-final"],
  WorkedSearch: ["canonical", "loading", "empty", "error-retriable", "error-final"],
  // The one pick of the tutor (UXS-54): Settings → Tutor with Jana or another character chosen, a custom name and a
  // refused name, and the pick that opens the first-session interview (UXS-10). The six characters (DSN-26) in every
  // pose of TABLE DSN-26b and its four speaking mouths, and the presence in each voice state (UXS-53), each also still.
  SettingsTutor: ["canonical", "error-retriable"],
  FirstRunTutorPick: ["canonical"],
  TutorCharacter: ["canonical", "reduced-motion"],
  TutorPresence: ["canonical", "reduced-motion"],
  // M45.d (D120): the help chips and the follow-up chips (ASM-28, UXS-68).
  NextStepChips: ["canonical"],
  // M33.a: Settings → Parent summary (UXS-33, TCH-12; a full week, too little to summarise, none), the summary as it
  // prints (DSN-22), Settings → Alerts (TCH-14) and Progress → Session history (UXS-48; the list, a session read-only,
  // a purged one, and the lock during a mock sitting).
  ParentSummary: ["canonical", "empty", "loading", "error-retriable"],
  PrintedReport: ["canonical"],
  Alerts: ["canonical", "empty", "loading", "error-retriable"],
  SessionHistory: ["canonical", "empty", "loading", "error-retriable", "locked"],
};

export { GalleryView, type GalleryState } from "./GalleryView.js";
