// Client store, pure reducer, delta queue, stream client and commands (M5; UIA-01 to UIA-07, API-20); profiles, the
// profile token and its renewal (UXS-09, UXS-29, SEC-19); the health panel's reads (OBS-15, ARC-26); the student's
// notes: the knows page, forgetting and the memory-use line (LRN-36, MEM-11, MEM-14, MEM-28); the subject map and the
// lesson player (UXS-22, UXS-23); the connectivity slice and the egress indicator state (UIA-23, UXS-06).
export * from "./store.js";
export { CueSync, PEN_LEAD_MS, cueReport, parseTarget, wordTime, type CaptionCue, type CaptionWord, type CueRecord, type CueTiming, type PenView, type PointerTarget, type PointerView, type WritingView } from "./pointer.js";
export { FRAME_MS, LoudnessTrack, MOUTH_SETTINGS, MouthFollower, PLAYBACK_RATE, frameLevels, type MouthSettings, type MouthShape } from "./mouth.js";
export { VoiceController, type VoicePlace, MICROPHONE_REASONS, PERMANENT_REASONS, microphoneReason, type VoiceAudio, type VoiceSocket, type VoiceState, type VoiceView, type TalkMode } from "./voice.js";
export { SpeechController, listedNote, type ListedNote, type LocalSpeech, type SpeechView, type ReadSource, type StudyNote, type SpeechPreferences } from "./speech.js";
export { answerInterview, readInterview, type InterviewAnswer, type InterviewCard, type InterviewView } from "./interview.js";
export { StepIdleWatch, openStepOf, reportStepIdle, type IdleTimers } from "./idle.js";
export { reduce, optimistic, markFailed, markForgotten, markSending, removeSketch } from "./reducer.js";
export { boundLine, moveVisual, selectBoardLine, stepBoard, type VisualMoveSource } from "./visuals.js";
export {
  EMPTY_KNOWS, KnowsController, MEMORY_READ_TOOLS, PREFERENCE_KEYS, PREFERENCE_VALUES, forgetNote, knowsReplyProblems, knowsViewOf, memoryReadCount, readKnows,
  type About, type Band, type Correction, type ForgetReason, type KnowsKc, type KnowsMisconception, type KnowsNote, type KnowsPreference, type KnowsReply, type KnowsReview,
  type KnowsView, type PreferenceKey, type Sharing,
} from "./memory.js";
export {
  BANDS, EMPTY_LESSON, EMPTY_MAP, KC_STATES, LessonController, SubjectMapController, bandCounts, checkResultProblems, isStepLesson, lessonProblems, readCheckResult, readLesson,
  readSubjectMap, subjectId, subjectMapProblems, syllabusCodes, topicLabel, type CheckBlockType, type CheckExplanation, type CheckPart, type CheckResult, type CheckState, type CheckVerdict, type KcState,
  type LessonBlock, type LessonPlayerView, type LessonView, type MapBand, type MapKc, type MapLesson, type MapSection, type MapStatus, type MapSyllabus, type MapTopic, type MapView,
  type PartAnswer, type PracticeItem, type StepAction, type SubjectMap, type SyllabusPoint, type VisualRef, type WorkedExampleView,
} from "./learn.js";
export { hydrate, type CoreSnapshot } from "./hydrate.js";
export { splitBlocks, type Blocks } from "./blocks.js";
export { DeltaQueue, coalesce, type Clock, type Envelope } from "./queue.js";
export {
  FamilySettings, ProfileController, type OpenState, type ProfileOptions, type ProfileTimers, type ProfilesView,
  type StudentPreferences,
} from "./profiles.js";
export { KNOWN_EVENTS, SessionController, StoreHolder, commandsFor, newSubjectStart, type Launch, type NewSubjectStart, type SessionOptions, type SessionTarget } from "./session.js";
export { StreamClient, type Endpoint, type StreamEnvelope, type StreamOptions } from "./stream/client.js";
export { CommandClient, CommandError, Unreachable } from "./stream/commands.js";
export { SseParser } from "./stream/sse.js";
export { clientId, ulid } from "./ids.js";
export { readEnvelope, UNKNOWN, type ReadResult } from "./tolerant.js";
export { CLIENT_KEYS } from "./generated/keys.js";
export {
  CLASS_BASES, HARDWARE_CLASSES, HEALTH_PROBLEMS, NO_CLASS_REASONS, hardwareReason, hardwareReport, healthProblems, installedModels, readDegraded,
  readHealthReport, savingPower, tutorAnswers, tutorCannotRun, tutorSetup, unverifiedSubjects, type HardwareReason, type HardwareReport, type HealthProblem, type HealthReport,
  type RuntimeBuild, type Shortfall, type TutorSetup,
} from "./health.js";
export {
  CLOUD_FALLBACK_NOTICES, CONSENT_FEATURES, CONSENT_NOTICE_VERSIONS, ConnectivityController, INDICATOR_ALIAS, INDICATOR_ICON, INDICATOR_STATES,
  ONLINE_FEATURES, activeEgress, canSendNow, clearSessions, cloudAnswered, emptyConnectivity, indicatorOf, queuedItems, reduceConnectivity,
  seedConnectivity, turnEgress, type CloudSubscription, type ConnectivityReply, type ConnectivitySlice, type EgressLedger, type EgressLedgerEntry,
  type EgressRec, type FeatureReply, type FeatureStatus, type Indicator, type IndicatorAlias, type IndicatorIcon, type IndicatorState, type Network,
  type SubscriptionApply,
} from "./connectivity.js";
export { captureRegionText, typedCapture, assertConfirmed, reviseTypedCapture, confirmTypedCapture, cancelTypedCapture, type CapturedQuestion, type CaptureSource, type CapturePurpose } from "./capture.js";
export { normaliseInput, INPUT_LIMITS, InputError, pastedQuestions, workingLines } from "./input.js";
export { boardLineLatex, canonicalDecimalCommas, convertMath, isMathShortcut, unitLatexOf, type EntryMode, type Conversion } from "./maths-input.js";
export { convertEntry, elementCaseSuggestion } from "./subject-input.js";
export { ledgerTable, ledgerTotals, journalFromText, LEDGER_COLUMNS, type LedgerTemplate, type LedgerTable } from "./ledger.js";
export { downloadState, modelManagerView, type ModelDownloadEvent, type ModelManagerView, type ModelRow, type ModelRowState } from "./models.js";
export { InstallationController, type ChooseInstallSource, type InstallationView, type InstallSourceKind } from "./installations.js";

export { DraftController } from "./drafts.js";
export {
  EMPTY_PLAN, EMPTY_PROGRESS, PlanController, ProgressController, gradeShown, kcSubjectCode, mockBandShown, nextBlock,
  type GradeShown, type MockBandShown, type PlanAlternative, type PlanBlock, type PlanChoice, type PlanState, type PlanView, type ProgressGrade, type ProgressState,
  type ProgressSubject, type ProgressView,
} from "./plans.js";
export {
  EMPTY_SEARCH, SearchController, markedRuns, matchOf, previewOf, queryWords, type SearchItem, type SearchMatch, type SearchState, type WorkedSolution,
} from "./search.js";

export { PhotoCommands, type Corner } from "./photo.js";

export { checkPhotoHeader } from "./photo-header.js";

export { SUBJECT_CODES, SUBJECT_NAMES, firstRunProfile, installedSubjects, subjectName, type InstalledSubject, type SubjectName } from "./setup.js";
export { ProblemReports, type NewProblemReport, type ProblemReport } from "./reports.js";
export { STAGE_2_SECTIONS, SettingsSections, readSettingsSections, type SettingsSection, type SettingsSectionsReply } from "./settings-sections.js";
export { ARTICLE_KEY_PREFIX, OfflineHelp, issueArticle, readHelp, searchHelp, type HelpArticle, type KnownIssue, type OfflineHelpReply } from "./help.js";
export {
  DUE_STATES, SESSION_GROUPS, duePractice, groupSessions, lastWorked, readSessions, recentSessions, refreshesDue, sessionGroupOf, type DueIdea, type RecentSession,
  type SessionGroup,
} from "./recent.js";
export {
  decideCrashReport, finishSetup, importProfile, parseAssets, parseNotices, readLicence, readSetup, serverVersion, shareWithSupport, sharedComputer, waitingCrashReports,
  type AssetEntry, type CrashReport, type LicenceStatus, type NoticeEntry, type SetupState,
} from "./support.js";
export { DAILY_GOAL_CHOICES, DEFAULT_DAILY_GOAL, DailyGoal, STUDY_ACTION_KINDS, goalProgress, type GoalProgress } from "./goal.js";
export { FOLLOW_UP_KINDS, HELP_KINDS, MAX_FOLLOW_UPS, TITLE_WORDS, chatTitle, followUps, helpTurn, mentionsAnswer, type FollowUpChip, type FollowUpKind, type HelpKind } from "./chips.js";
export { EMPTY_PRACTICE, PracticeController, settled, type PracticeMarked, type PracticeRevealed, type PracticeTry, type PracticeView } from "./practice.js";
export {
  EMPTY_MOCKS, LOCKED_STATES, MockController, examLock, pauseBudget, remainingAt, type ExamLock, type MockAnswer, type MockExam, type MockPaper, type MockResult,
  type MockSitting, type MockView, type SittingState,
} from "./mocks.js";
export {
  RESEARCH_SCOPES, agreesForItself, readConsents, readProfile, readTelemetrySchema, researchExport, switchConsent, type AgeBand, type ConsentState, type Profile,
  type ReportField, type ResearchScope, type StudyApproval, type TelemetrySummary,
} from "./studies.js";
export { waitForJob } from "./jobs.js";
export * from "./assessments.js";
export * from "./saved-questions.js";
export * from "./session-notes.js";
export {
  ALERT_KINDS, EMPTY_PARENT_VIEW, ParentController, conversationStarter, hoursAndMinutes, readAlerts, readDigest, type AlertKind, type AlertView,
  type DigestKc, type DigestMock, type DigestWatch, type ParentDigest, type ParentView,
} from "./parents.js";
export {
  EMPTY_HISTORY, HistoryController, historyStore, readHistoryList, readHistorySession, type HistoryEntry, type HistoryList, type HistorySession,
  type HistoryStep, type HistoryView,
} from "./history.js";
export * from "./ask-anything.js";
export { StudyWorkspaceController, EMPTY_STUDY, GENERATE_TOOLS, type GenerateTool, type StudyWorkspaceView, type StudyContracts, type PodcastAudio } from "./study-workspace.js";
export {
  EMPTY_EXAM_DATES, EMPTY_PAST_PAPERS, ExamDateController, PastPaperController, type ExamCountdown, type ExamDate, type ExamDateDraft, type ExamDateList,
  type ExamDatesView, type ExamReminder, type PaperSource, type PastPaperDraft, type PastPaperSubject, type PastPaperSummary, type PastPapersView, type PastPaperView,
} from "./past-papers.js";
export * from "./learning-journey.js";
