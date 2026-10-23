// A fake local core for the profile tests (UXS-09, UXS-29, SEC-19): profiles that open with a tap (no PIN anywhere,
// D86, D87), profile tokens the core can close (`expireTokens`: its idle auto-lock, or a restart), per-profile settings
// and one session per profile whose transcript and board carry that profile's canary text, listed by `GET /v1/sessions`
// once it exists, plus each profile's notes, level, subjects and consents for the knows page (LRN-36); the online
// features with their queues, the egress ledger and the cloud tutor's subscription (UXS-06, UXS-07, UXS-08, ARC-10,
// D70). It refuses what the real core refuses: a session, settings or notes request without the owner's profile token,
// another profile's note. Home's study plan, Progress and worked-solution search (UXS-12, UXS-27, UXS-51) as the
// core serves them since API 1.7: plans proposed, answered on the card route and changed into new proposals, a
// progress view a test sets, and a search over the fake's items with each item's solution on request.
import type { ConsentState, Health, ModelCatalogue, api_commands } from "@jana/contracts-ts";
import type { CloudSubscription, ConnectivityReply, EgressLedgerEntry, Network, SubscriptionApply } from "../src/connectivity.js";
import type { CoreSnapshot } from "../src/hydrate.js";
import type { KnowsKc, KnowsMisconception, KnowsNote, KnowsPreference, KnowsReply, KnowsReview } from "../src/memory.js";
import { PREFERENCE_VALUES } from "../src/memory.js";
import type { Launch } from "../src/session.js";

/** A note as a test gives it: the MemoryList fields, and any learner-view field it wants to set. */
export type FakeNote = Pick<KnowsNote, "note_id" | "text" | "created_ts" | "source"> & Partial<KnowsNote>;

/** A note in the learner view's shape. */
export function knowsNote(note: FakeNote): KnowsNote {
  return { status: "active", flagged: false, subject: null, updated_ts: note.created_ts, ...note };
}

export interface FakeProfile {
  profile_id: string;
  display_name: string;
  avatar: string;
  session_id: string;
  canary: string;
}

export interface Logged {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

const ulid = (n: number) => n.toString().padStart(26, "0");

/** A plan block as a test describes it: its kind, ideas and minutes. */
export interface FakeBlock {
  kind: api_commands.PlanBlock["kind"];
  kc_ids: string[];
  minutes: number;
  reason_code?: api_commands.PlanBlock["reason_code"];
}

/** The plan the fake proposes unless a test sets `planBlocks`: reviews, a main topic, mixed review, a look back. */
export const FAKE_BLOCKS: FakeBlock[] = [
  { kind: "warmup", kc_ids: ["kc.phy.o.motion.speed", "kc.phy.o.motion.velocity"], minutes: 5 },
  { kind: "main", kc_ids: ["kc.phy.o.forces.newton_second"], minutes: 20 },
  { kind: "mixed", kc_ids: ["kc.phy.o.motion.speed"], minutes: 5 },
  { kind: "reflect", kc_ids: [], minutes: 1 },
];

/** An empty progress view: nothing studied yet. */
export const EMPTY_PROGRESS_VIEW: api_commands.ProgressView = {
  subjects: [], time_studied: { minutes_7d: 0, sessions_7d: 0, minutes_total: 0 }, streak: { days: 0, freezes_left: 0, counted_today: false }, moved_today: [],
};

/** A mock paper as `GET /v1/mocks` lists it. */
export interface FakeMockPaper {
  paper_id: string;
  subject: "mathematics" | "physics" | "chemistry" | "biology" | "accounting";
  level: "O" | "A";
  title: string;
  paper_kind: "paper_1_objective" | "paper_2_structured" | "paper_3_structured" | "section_mock";
  duration_minutes: number;
  total_marks: number;
  questions: number;
  calculator: boolean;
}

/** One sitting in the fake: its state, active time and answers. */
export interface FakeSitting {
  exam_id: string;
  paper_id: string;
  profile_id: string;
  state: "ready" | "in_progress" | "paused" | "interrupted" | "submitted" | "marked" | "reviewed" | "abandoned";
  duration_ms: number;
  extra: 0 | 25 | 50;
  elapsed_ms: number;
  running_since: number | null;
  pause_since: number | null;
  pauses: { at: string; length_ms: number }[];
  interruptions: { at: string; remaining_ms: number }[];
  answers: Record<string, { answer: unknown; flagged: boolean }>;
  result: Record<string, unknown> | null;
}

export const PROFILES: FakeProfile[] = [
  { profile_id: `prf_${ulid(1)}`, display_name: "Ada", avatar: "avatar-1", session_id: `ses_${ulid(1)}`, canary: "CANARY-ADA-q7x9 momentum of the red trolley" },
  { profile_id: `prf_${ulid(2)}`, display_name: "Ben", avatar: "avatar-2", session_id: `ses_${ulid(2)}`, canary: "CANARY-BEN-k3m1 resistance in series" },
  { profile_id: `prf_${ulid(3)}`, display_name: "Chi", avatar: "avatar-3", session_id: `ses_${ulid(3)}`, canary: "CANARY-CHI-z8w2 titration end point" },
];

function snapshot(profile: FakeProfile): CoreSnapshot {
  const turn = `trn_${profile.session_id.slice(4)}`;
  const part = `prt_${profile.session_id.slice(4)}`;
  const board = `brd_${profile.session_id.slice(4)}`;
  return {
    session: { session_id: profile.session_id, title: profile.canary, mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false },
    cursor: { epoch: "ep_profiles", seq: 0 },
    messages: [
      { role: "student", message_id: `msg_${ulid(10)}`, client_message_id: null, turn_id: turn, content: [{ type: "text", text: `My question: ${profile.canary}` }], ts: 1 },
      {
        role: "tutor", message_id: `msg_${ulid(11)}`, turn_id: turn, part_ids: [part], status: "complete", stop_reason: "completed", degraded: false,
        degraded_reason: null, error: null, ts: 2, intent: "ask", mode: "guided", user_message_id: `msg_${ulid(10)}`, client_message_id: null,
        phase: null, hint_rung: null, usage: null, elapsed_ms: 1000, verification: null,
      },
    ],
    parts: { [part]: { part_id: part, turn_id: turn, kind: "text", index: 0, status: "complete", text: `The tutor says: ${profile.canary} \\(p = mv\\)` } },
    boards: {
      [board]: {
        board_id: board, part_id: part, problem: { text: profile.canary, latex: null }, knowns: [], unknowns: [], conventions: [],
        steps: { stp_1: { step_id: "stp_1", index: 0, latex: `\\text{${profile.canary}}`, reason: profile.canary, owner: "student", status: "final", check_id: null, error: null } },
        order: ["stp_1"], awaiting: null, highlight: null,
      },
    },
    visuals: {},
    open_requests: [],
    active_turn: null,
  };
}

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function error(status: number, code: string, extra: Record<string, unknown> = {}): Response {
  return json(status, { error: { code, message: code, retryable: code === "rate_limited", action_taken: false, request_id: "req_x", ...extra } });
}

/** A consent state as the core lists it: `effective` only when granted (and, here, its feature on). */
export function consent(scope: string, effective: boolean): ConsentState {
  return {
    scope: scope as ConsentState["scope"], granted: effective, granted_by_role: effective ? "guardian" : null,
    method: effective ? "checkout_guardian" : null, notice_version: effective ? "1" : null,
    granted_at: effective ? "2026-10-01T09:00:00.000Z" : null, effective, paused: false,
  };
}

export class FakeProfileCore {
  readonly log: Logged[] = [];
  readonly profiles = PROFILES.map((p) => ({ ...p }));
  readonly tokens = new Map<string, string>(); // profile token -> profile id
  /** The sessions created so far, by session id, with the subject and topic of the newest create: `GET /v1/sessions`
   * lists them and the snapshot carries that subject (API-23). Each profile has one session in this fake. */
  readonly sessionsMade = new Map<string, { subject: string; topic_id: string | null }>();
  /** Turns started on the profile's session (the tutor never answers them). */
  turnsStarted = 0;
  readonly settings = new Map<string, Record<string, unknown>>();
  /** The S2 online features, each off on a fresh install (ARC-07a order). */
  readonly features: Record<string, boolean> = { cloud_tier: false, downloads: false, update_checks: false, telemetry: false, crash_reports: false };
  /** The network state; null answers `off` while every feature is off and `offline` otherwise. */
  network: Network | null = null;
  /** Items waiting in the outbox per feature (proposed `queued_items`), and when each feature last sent. */
  readonly queued: Record<string, number> = {};
  readonly lastSent: Record<string, string | null> = {};
  /** The egress ledger's rows (proposed `EgressLedger`). */
  readonly ledger: EgressLedgerEntry[] = [];
  /** The device consents the switches recorded (`telemetry`, `crash_reports`): true granted, false withdrawn. */
  readonly deviceConsents = new Map<string, boolean>();
  /** The cloud tutor's subscription (proposed `CloudSubscription`, D70). */
  subscription: CloudSubscription = { state: "none", subscription_id: null, period_end: null, allowance_used_up: false, profiles: [] };
  /** Profiles whose learner database a newer app wrote: unlock is refused before a token is issued (DAT-12). */
  readonly newerApp = new Set<string>();
  /** What `GET /v1/packs` lists: each pack as the core verified it (CUR-08). */
  readonly packs: { pack_id: string; subject: string; level: "O" | "A"; version: string; signature_ok: boolean; size_bytes: number }[] = [];
  /** What `GET /v1/health` answers: tests seed components and readiness (OBS-15, ARC-26). */
  health: Health = { status: "ok", components: { core: "ok", runtime: "ok" }, readiness: "ready" };
  /** What `GET /v1/models` answers: the hardware class and why, and the installed models (OBS-15). */
  models: ModelCatalogue = {
    installed: [{ model_id: "synthetic-large", pack_version: "0.1.0", serving: true }],
    available: [],
    assignment: { fast: "synthetic-large", strong: "synthetic-large" },
    recommended: { fast: "synthetic-large", strong: "synthetic-large", reason_key: "hardware_class.mid.predicted" },
  };
  /** Requests whose path matches wait here until the test releases them. */
  readonly gates = new Map<string, Promise<void>>();
  /** Each profile's notes (synthetic): `GET /v1/profiles/{id}/memory` lists the MemoryList fields, the learner view
   * every field (a note given without them is active, unflagged and has no subject). */
  readonly notes = new Map<string, FakeNote[]>();
  /** Each profile's learner-view sections (G90): KCs, misconceptions, preferences and open review items. */
  readonly kcs = new Map<string, KnowsKc[]>();
  readonly misconceptions = new Map<string, KnowsMisconception[]>();
  readonly preferences = new Map<string, KnowsPreference[]>();
  readonly reviews = new Map<string, KnowsReview[]>();
  /** Answers the learner-view corrections with this error code instead, when set. */
  correctFails: string | null = null;
  /** Answers `GET .../knows` with this body instead, when set (a malformed reply). */
  knowsBody: unknown = null;
  /** Each profile's level, subjects and exam date. */
  readonly about = new Map<string, { level: "O" | "A"; subjects: string[]; exam_date: string | null }>();
  /** Each profile's consent states (`GET /v1/profiles/{id}/consents`). */
  readonly consents = new Map<string, ConsentState[]>();
  /** Answers `DELETE /v1/memory/{id}` with this error code instead of deleting, when set. */
  deleteFails: string | null = null;
  /** Paths answered with a 503 (a read that fails). */
  readonly unavailable = new Set<string>();
  /** The subject maps (M13.g, UXS-22) by subject id, and the lessons (UXS-23) by lesson id: each profile reads the same
   * curriculum, with `mapFor` to give one profile its own KC states. */
  readonly maps = new Map<string, unknown>();
  mapFor: ((profileId: string, subjectId: string) => unknown) | null = null;
  readonly lessons = new Map<string, Record<string, unknown>>();
  /** Saved lesson positions per profile and lesson. */
  readonly positions = new Map<string, { block_index: number; lesson_version: string; updated_ts: number }>();
  /** Answers a position save with this error code instead, when set. */
  positionFails: string | null = null;
  /** How a quick check is marked: by default every answer is correct. */
  mark: (itemId: string, parts: { part_id: string }[]) => { verdict: string; category: string | null } = () => ({ verdict: "correct", category: null });
  openStreams = 0;
  /** Every `POST /v1/profiles` body, in order. */
  readonly created: Record<string, unknown>[] = [];
  /** `GET /v1/licence`: a family computer with no licence file, the free offline product (D84). */
  licence: Record<string, unknown> = {
    state: "none", offer: "free", licence_id: null, seats: null, expires_at: null, channel: "dev", install_kind: "family", clock_behind: false,
    entitlements: {
      lessons: true, practice: true, tool_checks: true, progress: true, local_tutor: true, mock_exams: true, offline_study_area: true, content_updates: "all",
      student_profiles: "all", parent_summary: false, cloud_tier: "available", study_materials: "available", cloud_backup: "available", multi_device: "available",
      parent_remote_view: "available", web_client: "available",
    },
  };
  /** Crash reports waiting for "Send this report?", listed only while `crash_reports` is on (OBS-17). */
  readonly crashReports: { crash_id: string; [k: string]: unknown }[] = [];
  readonly crashDecisions: string[] = [];
  /** First run finished ("Start learning" recorded); the fake starts with students who have been through it. */
  setupDone = true;
  /** The hand-off's first-session interview (UXS-10): its question cards, or null for a core that serves none. */
  interview: { question_id: string; card: Record<string, unknown> }[] | null = null;
  /** Every interview answer, in order. */
  readonly interviewAnswers: { question_id: string; answer: Record<string, unknown> }[] = [];
  readonly imports: Record<string, unknown>[] = [];
  readonly supportShares: string[] = [];
  /** Practice sets (API-27): served as the core serves them since M16 (a mark carries its reflection card); a test of an
   * older core turns this off and the route answers `not_found`. */
  practiceServed = true;
  practiceItems: (Record<string, unknown> & { item_id: string })[] = [];
  private practiceAt = 0;
  private practiceTotal = 0;
  private practiceAttempts = 0;
  /** Misses on the question shown: the first keeps it for a second try (ASM-28). */
  private practiceMisses = 0;
  /** The worked answer the fake core gives after a second miss or on Don't know (ASM-28). */
  worked = { worked_example_id: "we.fake", problem: "The question", steps: [{ n: 1, latex: "v = \\frac{d}{t}", reason: "Speed is distance over time", check_id: "chk_fake_step" }],
    final_answer: { latex: "1.5\\ \\mathrm{m/s}", check_id: "chk_fake_key" }, faded_steps: [] as number[] };
  readonly helped: string[] = [];
  /** Mock exams (API-27, UXS-25; `GET /v1/mocks`, `MockList`, D93): the papers on this
   * computer, the questions every fake paper holds, and how the fake marks an answer. The clock is the fake's `now`;
   * it counts active time only, like the core (ASM-16). Off for an older core, which answers `not_found`. */
  mocksServed = true;
  mockPapers: FakeMockPaper[] = [];
  mockQuestions: (Record<string, unknown> & { item_id: string; kc_ids: string[]; marks?: number })[] = [];
  mockRight: (questionId: string, answer: unknown) => boolean = () => true;
  /** Questions whose criterion the fake leaves "not marked automatically" (ASM-17). */
  mockUnresolved: string[] = [];
  mockBand: Record<string, unknown> | null = null;
  readonly mockSittings: FakeSitting[] = [];
  readonly mockSignals: { kind: string; amount: number }[] = [];
  readonly reviewed: string[] = [];
  /** Plans (UXS-12, D99): every proposal in order; a test sets the blocks proposed and the alternatives. */
  plansServed = true;
  readonly plans: api_commands.PlanView[] = [];
  planBlocks: FakeBlock[] = FAKE_BLOCKS;
  planAlternatives: string[] = ["kc.phy.o.forces.mass_weight", "kc.phy.o.energy.kinetic", "kc.phy.o.motion.acceleration"];
  /** Each `client_request_id` and the plan it made: a retried request gets the same plan (API-14 idempotency). */
  readonly planRequests = new Map<string, string>();
  /** The plan card answers in order (`start`, `change:alt_1`, `skipped`...). */
  readonly planAnswers: string[] = [];
  /** `GET /v1/progress` (UXS-27); null for an older core, which answers `not_found`. */
  progress: api_commands.ProgressView | null = EMPTY_PROGRESS_VIEW;
  /** Worked-solution search (UXS-51): the items a query can match, each with its solution; the reserved ones never
   * match and their solutions are not found, as the core filters them. Queries and solution reads are recorded. */
  searchServed = true;
  searchItems: (Record<string, unknown> & { item_id: string; stem: string; kc_ids: string[]; solution?: api_commands.WorkedExampleView; reserved?: boolean })[] = [];
  readonly searches: string[] = [];
  readonly solutionsRead: string[] = [];
  /** Profiles aged 18 or over (they grant their own research consent, D43); every other profile is a minor. */
  readonly adults = new Set<string>();
  readonly consentSwitches: { scope: string; action: string; guardian_agreed?: true }[] = [];
  readonly exports: Record<string, unknown>[] = [];
  /** `GET /v1/telemetry/schema`: a synthetic report schema in the published contract's shape (OBS-20). */
  telemetrySchema: Record<string, unknown> = {
    $id: "https://jana.dev/contracts/trace/telemetry", type: "object",
    properties: {
      report_id: { type: "string" }, app_version: { type: "string" }, channel: { enum: ["dev", "pilot", "stable"] }, os_family: { enum: ["windows", "macos", "linux"] },
      days: { type: "integer", minimum: 1, maximum: 14 }, metrics: { $ref: "#/$defs/metrics" }, labels: { type: "object", properties: { role: { enum: ["coach", "solver"] } } },
    },
    $defs: { metrics: { type: "object", properties: { ttft_ms: { $ref: "#/$defs/histogram" }, tool_calls: { $ref: "#/$defs/histogram" } } }, histogram: { type: "object" } },
  };
  /** The composers' saved drafts, by session and slot. */
  readonly drafts = new Map<string, { document: Record<string, unknown>; revision: number }>();
  /** The offline help (OPS-23, `GET /v1/help`): served as the core serves it since M24; off for an older core. Each
   * article is its id and step count; the reply carries catalogue keys, as the core's does (LOC-01, D93). */
  helpServed = true;
  helpArticles: { id: string; steps: number }[] = [{ id: "slow", steps: 3 }, { id: "usb", steps: 3 }];
  knownIssues: { issue_id: string; title_key: string; help_article_id: string; fixed_in?: string;
    affects: { artefact_kind: "app"; artefact_id: string; versions: string[] } }[] = [];
  helpContacts: string[] = [];
  /** The Settings sections the core lists (UXS-46, `GET /v1/settings/sections`), as the core's settings_sections
   * gives them for its build stage (stage 2 by default; stage 3 adds three); null for a core without the route. */
  sectionsStage: "S2" | "S3" | null = "S2";
  private minted = 0;

  readonly launch: Launch = { endpoint: async () => ({ baseUrl: "http://core.test", token: "launch-token" }) };

  constructor(private readonly now: () => number = () => Date.now()) {
    for (const p of this.profiles) {
      this.settings.set(p.profile_id, {
        low_power: false, text_scale: 1, locale: "en", memory_saving: true, notifications: false,
        reduced_motion: false, read_aloud: false, easy_read: false, extra_time_percent: 0,
      });
      this.notes.set(p.profile_id, []);
      for (const map of [this.kcs, this.misconceptions, this.preferences, this.reviews] as Map<string, unknown[]>[]) map.set(p.profile_id, []);
      this.about.set(p.profile_id, { level: "O", subjects: ["physics"], exam_date: null });
      this.consents.set(p.profile_id, ["cloud_tier", "research_use"].map((scope) => consent(scope, false)));
    }
  }

  /** The learner view as the core answers it (G90): notes newest first, sharing from the effective consents. */
  knowsReply(profileId: string, _viewer: "student"): KnowsReply {
    const effective = new Set((this.consents.get(profileId) ?? []).filter((c) => c.effective).map((c) => c.scope));
    const notes = (this.notes.get(profileId) ?? []).map(knowsNote).sort((a, b) => b.created_ts - a.created_ts);
    return {
      profile_id: profileId, about: this.about.get(profileId) ?? null, kcs: this.kcs.get(profileId) ?? [],
      misconceptions: this.misconceptions.get(profileId) ?? [], preferences: this.preferences.get(profileId) ?? [], notes,
      reviews: this.reviews.get(profileId) ?? [], memory_saving: this.settings.get(profileId)?.memory_saving !== false,
      sharing: this.unavailable.has(`/v1/profiles/${profileId}/consents`) ? null
        : { backup: effective.has("cloud_backup"), devices: effective.has("multi_device"), parent_view: effective.has("parent_remote_view"), cloud_tutor: effective.has("cloud_tier") },
    };
  }

  /** `ConnectivityState` with the proposed per-feature fields. */
  connectivity(): ConnectivityReply {
    const network = this.network ?? (Object.values(this.features).some(Boolean) ? "offline" : "off");
    const features = Object.fromEntries(Object.entries(this.features).map(([f, on]) => [f, {
      enabled: on, state: (this.queued[f] ?? 0) > 0 ? "queued" as const : "idle" as const, queued_items: this.queued[f] ?? 0, last_sent_at: this.lastSent[f] ?? null,
    }]));
    return { network, features };
  }

  private setConsent(profileId: string, scope: string, granted: boolean): void {
    const list = (this.consents.get(profileId) ?? []).filter((c) => c.scope !== scope);
    this.consents.set(profileId, [...list, consent(scope, granted)]);
  }

  /** The core closes every profile, as its idle auto-lock does after a quiet spell or a restart does (SEC-19). */
  expireTokens(): void {
    this.tokens.clear();
  }

  private readonly streamEnds = new Set<() => void>();

  /** Every open stream ends, as when the core restarts. */
  dropStreams(): void {
    for (const end of [...this.streamEnds]) end();
  }

  tokenOf(profileId: string): string | undefined {
    return [...this.tokens].find(([, id]) => id === profileId)?.[0];
  }

  private mint(prefix: string): string {
    this.minted += 1;
    return `${prefix}${this.minted.toString().padStart(40, "x")}`;
  }

  /** Release a request held by a gate. */
  hold(path: string): () => void {
    let release = () => {};
    this.gates.set(path, new Promise<void>((r) => (release = r)));
    return () => {
      this.gates.delete(path);
      release();
    };
  }

  fetch = async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));
    const method = init.method ?? "GET";
    const headers = { ...(init.headers as Record<string, string> | undefined) };
    const body = typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    this.log.push({ method, path: url.pathname, headers, body });
    await this.gates.get(url.pathname);
    if (headers.authorization !== "Bearer launch-token") return error(401, "unauthorized");
    if (this.unavailable.has(url.pathname)) return error(503, "core_starting");
    const profile = this.tokens.get(headers["x-profile-token"] ?? "") ?? null;
    const path = url.pathname;
    let m: RegExpExecArray | null;

    if (method === "GET" && path === "/v1/profiles") {
      // An extra field the client must not show: the picker keeps only name, avatar and whether a PIN is set.
      return json(200, { profiles: this.profiles.map((p) => ({ profile_id: p.profile_id, display_name: p.display_name, avatar: p.avatar, level: "LEAK-LEVEL" })) });
    }
    if (method === "GET" && path === "/v1/packs") return json(200, { packs: this.packs });
    if (method === "GET" && path === "/v1/health") return json(200, this.health);
    if (method === "GET" && path === "/v1/help") {
      if (!this.helpServed) return error(404, "not_found");
      const articles = this.helpArticles.map(({ id, steps }) => ({
        id, title_key: `help.article.${id}.title`, body_key: `help.article.${id}.body`,
        step_keys: Array.from({ length: steps }, (_, n) => `help.article.${id}.step_${n + 1}`), app_major_minor: "0.1",
      }));
      return json(200, {
        app_version: "0.1.0", channel: "stable", device_id: "dev_synthetic01", articles, known_issues: this.knownIssues, contacts: this.helpContacts, health: { status: "ok", components: {}, readiness: "ready" },
        safety: { sequence: 0, pending_sequence: 0, ignored_entries: 0, entries: [] },
      });
    }
    if (method === "GET" && path === "/v1/settings/sections") {
      if (this.sectionsStage === null) return error(404, "not_found");
      // As agent_core.config.support.settings_sections lists them.
      const ids = ["online_features", "profiles", "tutor_models", "content", "egress", "accessibility_language", "study", "tutor", "data_export", "licence", "help", "about",
        ...(this.sectionsStage === "S3" ? ["parent_summary", "alerts", "voice"] : [])];
      return json(200, { stage: this.sectionsStage, sections: ids.map((id) => ({ id, gate: "open", offline: true, states: ["ready", "empty", "error"] })) });
    }
    if (method === "GET" && path === "/v1/models") return json(200, this.models);
    if (method === "POST" && (m = /^\/v1\/profiles\/([^/]+)\/open$/.exec(path))) {
      const target = this.profiles.find((p) => p.profile_id === m![1]);
      if (target === undefined) return error(404, "not_found");
      if (this.newerApp.has(target.profile_id)) return error(426, "upgrade_required", { details: { message_key: "profile.newer_app" } });
      const token = this.mint("pt_");
      this.tokens.set(token, target.profile_id);
      return json(200, { profile_token: token, expires_in_s: 600 });
    }
    if (method === "POST" && (m = /^\/v1\/profiles\/([^/]+)\/close$/.exec(path))) {
      if (profile !== m[1]) return error(404, "not_found");
      for (const [token, id] of [...this.tokens]) if (id === profile) this.tokens.delete(token);
      return new Response(null, { status: 204 });
    }
    if (method === "GET" && path === "/v1/connectivity") return json(200, this.connectivity());
    if (method === "PATCH" && path === "/v1/connectivity") {
      const asked = (body as { features: Record<string, boolean> }).features;
      if (Object.keys(asked).some((f) => !(f in this.features))) return error(422, "validation_failed");
      Object.assign(this.features, asked);
      // The switch of a device scope is its consent: recorded with it, withdrawn with it (ARC-11).
      for (const [feature, on] of Object.entries(asked)) {
        if (feature === "telemetry" || feature === "crash_reports") this.deviceConsents.set(feature, on);
        if (!on) this.queued[feature] = 0;
      }
      return json(200, this.connectivity());
    }
    if (method === "POST" && path === "/v1/connectivity/send-now") {
      const network = this.connectivity().network;
      if (network !== "online" && network !== "metered") return error(503, "network_unavailable");
      for (const [feature, count] of Object.entries(this.queued)) {
        if (count > 0 && this.features[feature]) {
          this.queued[feature] = 0;
          this.lastSent[feature] = "2026-10-13T09:00:00.000Z";
        }
      }
      return json(200, this.connectivity());
    }
    if (method === "GET" && path === "/v1/connectivity/ledger") return json(200, { retention_days: 90, entries: this.ledger });
    // Settings → Licence and About, crash reports, first run's step and restoring a profile (launch authority, D86).
    if (method === "GET" && path === "/v1/licence") return json(200, this.licence);
    if (method === "GET" && path === "/v1/meta") return json(200, { protocol: { major: 1, min_minor: 0, max_minor: 0 }, server_version: "0.1.0-fake", epoch: "ep_profiles", deployment: "local", capabilities: [], deprecated: [] });
    if (method === "GET" && path === "/v1/crash-reports") return json(200, { reports: this.features.crash_reports ? this.crashReports : [] });
    if (method === "POST" && (m = /^\/v1\/crash-reports\/([^/]+)\/(send|dismiss)$/.exec(path))) {
      const at = this.crashReports.findIndex((r) => r.crash_id === m![1]);
      if (at < 0) return error(404, "not_found");
      if (m[2] === "send" && !this.features.crash_reports) return error(409, "feature_disabled");
      this.crashDecisions.push(`${m[1]}:${m[2]}`);
      this.crashReports.splice(at, 1);
      return new Response(null, { status: 204 });
    }
    if (path === "/v1/setup") {
      if (method === "PUT") {
        if (this.profiles.length === 0) return error(422, "validation_failed");
        this.setupDone = true;
      }
      return json(200, { step: this.setupDone ? "done" : "students", profiles: this.profiles.length, completed_at: this.setupDone ? "2026-10-15T09:00:00.000Z" : null });
    }
    if (path === "/v1/interview" || path.startsWith("/v1/interview/")) {
      if (profile === null) return error(401, "profile_token_expired");
      const questions = this.interview;
      if (questions === null) return error(404, "not_found");
      const view = () => {
        const next = questions[this.interviewAnswers.length] ?? null;
        return { total: questions.length, answered: this.interviewAnswers.length, done: next === null, question: next };
      };
      if (method === "POST" && (m = /^\/v1\/interview\/([^/]+)\/answer$/.exec(path))) {
        if (questions[this.interviewAnswers.length]?.question_id !== m[1]) return error(422, "validation_failed");
        this.interviewAnswers.push({ question_id: m[1]!, answer: (body as { answer: Record<string, unknown> }).answer });
      }
      return json(200, view());
    }
    if (method === "POST" && path === "/v1/profiles/import") {
      this.imports.push(body as Record<string, unknown>);
      return json(202, { job_id: `job_${ulid(90)}`, queued_until_online: false });
    }
    if (method === "GET" && path === `/v1/jobs/job_${ulid(90)}`) return json(200, {
      job_id: `job_${ulid(90)}`, kind: "import", state: "done", progress: null,
      result_ref: `prf_${ulid(99)}`, error: null,
    });
    if (method === "POST" && (m = /^\/v1\/sessions\/([^/]+)\/support-share$/.exec(path))) {
      if (profile === null) return error(401, "profile_token_expired");
      if (this.profiles.find((p) => p.profile_id === profile)?.session_id !== m[1]) return error(404, "not_found");
      this.supportShares.push(m[1]!);
      return new Response(null, { status: 204 });
    }
    if (path === "/v1/mocks" || path.startsWith("/v1/mocks/")) return this.mocks(method, path, body, profile);
    // Practice sets (API-27): served only when `practiceServed`; marked with `mark`, the next item with every mark.
    if (path.startsWith("/v1/practice/sets")) {
      if (profile === null) return error(401, "profile_token_expired");
      if (!this.practiceServed) return error(404, "not_found");
      if (this.mockLocked(profile)) return error(423, "tutor_locked");
      if (method === "GET" && (m = /^\/v1\/practice\/sets\/([^/]+)$/.exec(path))) {
        this.practiceAt = 0;
        this.practiceMisses = 0;
        this.practiceTotal = this.practiceItems.length;
        return json(200, { set_id: m[1], items_total: this.practiceTotal, current_item: this.practiceItems[0] ?? null });
      }
      if (method === "POST" && path === "/v1/practice/sets") {
        const asked = body as { size: number };
        this.practiceAt = 0;
        this.practiceMisses = 0;
        this.practiceTotal = Math.min(asked.size, this.practiceItems.length);
        return json(200, { set_id: `set_${ulid(70)}`, items_total: this.practiceTotal, current_item: this.practiceItems[0] ?? null });
      }
      if (method === "POST" && (m = /^\/v1\/practice\/sets\/([^/]+)\/answers$/.exec(path))) {
        const asked = body as { item_id: string; answer: { parts: { part_id: string }[] } };
        const marked = this.mark(asked.item_id, asked.answer.parts);
        const item = this.practiceItems.find((i) => i.item_id === asked.item_id) as { kc_ids: string[] } | undefined;
        const right = marked.verdict === "correct";
        // As the core marks practice since M45.d (ASM-28): a first miss keeps the question for a second try and shows
        // no answer; the second miss carries the worked answer and moves on, like a settled answer.
        const missed = marked.verdict === "incorrect" || marked.verdict === "partially_correct";
        const firstMiss = missed && this.practiceMisses === 0;
        if (firstMiss) this.practiceMisses = 1;
        else { this.practiceAt += 1; this.practiceMisses = 0; }
        const next = firstMiss ? (this.practiceItems[this.practiceAt] ?? null) : this.practiceAt < this.practiceTotal ? this.practiceItems[this.practiceAt] ?? null : null;
        this.practiceAttempts += 1;
        return json(200, {
          ...(missed && !firstMiss ? { worked: this.worked } : {}),
          attempt_id: `att_${ulid(80 + this.practiceAttempts)}`, verdict: marked.verdict, marks_awarded: right ? 1 : 0, marks_total: 1, feedback_key: `practice.feedback.${marked.verdict}`,
          first_error: marked.category === null ? null : { category: marked.category, message_key: `board.error.${marked.category}` },
          mastery_change: { kc_id: item?.kc_ids[0] ?? "kc", band_before: "learning", band_after: right ? "secure" : "learning" }, next_item: next,
          reflection: { card_type: "reflection", did: "Your response was checked.", right: "Compare the criteria below.", next_goal: "The next question.",
            marks: [{ criterion: "The answer", type: "independent", awarded: right }] },
        });
      }
      if (method === "POST" && /^\/v1\/practice\/sets\/[^/]+\/reveal$/.test(path)) {
        // Don't know (ASM-28): the worked answer, then the next question; nothing marked.
        const asked = body as { item_id: string };
        const item = this.practiceItems.find((i) => i.item_id === asked.item_id) as { kc_ids: string[] } | undefined;
        this.practiceAt += 1;
        this.practiceMisses = 0;
        const next = this.practiceAt < this.practiceTotal ? this.practiceItems[this.practiceAt] ?? null : null;
        return json(200, { item_id: asked.item_id, worked: this.worked, mastery_change: { kc_id: item?.kc_ids[0] ?? "kc", band_before: "learning", band_after: "learning" }, next_item: next });
      }
      if (method === "POST" && /^\/v1\/practice\/sets\/[^/]+\/help$/.test(path)) {
        const owner = this.profiles.find((p) => p.profile_id === profile)!;
        this.helped.push((body as { item_id: string }).item_id);
        return json(200, { session_id: owner.session_id, cursor: { epoch: "ep_profiles", seq: 0 } });
      }
      return error(404, "not_found");
    }
    if (path === "/v1/subscription") {
      if (method === "POST") {
        const apply = body as SubscriptionApply;
        for (const c of apply.consents) this.setConsent(c.profile_id, "cloud_tier", true);
        const recorded = new Set(apply.consents.map((c) => c.profile_id));
        const profiles = this.subscription.profiles.map((p) => (recorded.has(p.profile_id) ? { ...p, consent: "recorded" as const } : p));
        const waiting = profiles.some((p) => p.consent === "needed");
        this.subscription = { ...this.subscription, profiles, state: waiting ? "pending_consent" : "active" };
        this.features.cloud_tier = !waiting;
      } else if (method === "DELETE") {
        for (const p of this.subscription.profiles) this.setConsent(p.profile_id, "cloud_tier", false);
        this.subscription = { ...this.subscription, state: "ended", profiles: [] };
        this.features.cloud_tier = false;
      }
      return json(200, this.subscription);
    }
    if ((m = /^\/v1\/profiles\/([^/]+)\/settings$/.exec(path))) {
      if (profile !== m[1]) return profile === null ? error(401, "profile_token_expired") : error(404, "not_found");
      const settings = this.settings.get(profile)!;
      if (method === "PATCH") Object.assign(settings, body as Record<string, unknown>);
      return json(200, settings);
    }
    if (method === "GET" && (m = /^\/v1\/profiles\/([^/]+)\/memory$/.exec(path))) {
      if (profile !== m[1]) return profile === null ? error(401, "profile_token_expired") : error(404, "not_found");
      const listed = (this.notes.get(profile) ?? []).map((n) => ({ note_id: n.note_id, text: n.text, created_ts: n.created_ts, source: n.source === "student" ? "student" : "reflector" }));
      return json(200, { notes: listed });
    }
    // The learner view and its corrections (G90): the owner's profile token.
    if ((m = /^\/v1\/profiles\/([^/]+)\/(knows|memory\/reviews\/[^/]+|memory\/[^/]+\/dispute|misconceptions\/[^/]+\/correction|preferences\/[^/]+)$/.exec(path))) {
      const target = m[1]!;
      const viewer = profile === target ? "student" : null;
      if (viewer === null || !this.profiles.some((p) => p.profile_id === target)) return error(404, "not_found");
      const rest = m[2]!;
      if (method !== "GET" && this.correctFails !== null) return error(this.correctFails === "not_found" ? 404 : 503, this.correctFails);
      const reply = (): Response => json(200, this.knowsReply(target, viewer));
      if (method === "GET" && rest === "knows") return this.knowsBody !== null ? json(200, this.knowsBody) : reply();
      let r: RegExpExecArray | null;
      if (method === "POST" && (r = /^memory\/reviews\/([^/]+)$/.exec(rest))) {
        const reviews = this.reviews.get(target)!;
        const item = reviews.find((i) => i.review_id === decodeURIComponent(r![1]!));
        if (item === undefined) return error(404, "not_found");
        const answer = body as { accept: boolean; pending_version: string; target_version: string | null };
        if (answer.pending_version !== item.pending_version || answer.target_version !== item.target_version) {
          return error(409, "review_changed", { details: { review: item } });
        }
        reviews.splice(reviews.indexOf(item), 1);
        const notes = this.notes.get(target)!;
        const drop = (id: string | undefined) => {
          const index = notes.findIndex((n) => n.note_id === id);
          if (index >= 0) notes.splice(index, 1);
        };
        if (item.kind === "replace" && answer.accept && item.pending !== null) {
          drop(item.target?.note_id);
          notes.push({ ...item.pending, status: "active" });
        } else if (item.kind === "drop" && answer.accept) drop(item.target?.note_id);
        return reply();
      }
      if (method === "POST" && (r = /^memory\/([^/]+)\/dispute$/.exec(rest))) {
        const notes = this.notes.get(target)!;
        const index = notes.findIndex((n) => n.note_id === decodeURIComponent(r![1]!));
        if (index < 0) return error(404, "not_found");
        notes.splice(index, 1);
        return reply();
      }
      if (method === "POST" && (r = /^misconceptions\/([^/]+)\/correction$/.exec(rest))) {
        const list = this.misconceptions.get(target)!;
        const index = list.findIndex((x) => x.misconception_id === decodeURIComponent(r![1]!));
        if (index < 0 || (body as { action?: string }).action !== "dispute") return error(404, "not_found");
        list.splice(index, 1);
        return reply();
      }
      if (method === "PATCH" && (r = /^preferences\/([^/]+)$/.exec(rest))) {
        const key = decodeURIComponent(r[1]!) as keyof typeof PREFERENCE_VALUES;
        if (!(key in PREFERENCE_VALUES)) return error(404, "not_found");
        const value = (body as { value: string | boolean | null }).value;
        const list = this.preferences.get(target)!.filter((p) => p.key !== key);
        if (value !== null) {
          if (!(PREFERENCE_VALUES[key] as readonly unknown[]).includes(value)) return error(422, "validation_failed");
          list.unshift({ key, value, source: "override" });
        }
        this.preferences.set(target, list);
        return reply();
      }
      return error(404, "not_found");
    }
    if (method === "DELETE" && (m = /^\/v1\/memory\/([^/]+)$/.exec(path))) {
      if (profile === null) return error(401, "profile_token_expired");
      if (this.deleteFails !== null) return error(this.deleteFails === "not_found" ? 404 : 503, this.deleteFails);
      const mine = this.notes.get(profile) ?? [];
      const index = mine.findIndex((n) => n.note_id === decodeURIComponent(m![1]!));
      if (index < 0) return error(404, "not_found"); // another profile's note is indistinguishable from none
      mine.splice(index, 1);
      return new Response(null, { status: 204 });
    }
    if (method === "GET" && (m = /^\/v1\/profiles\/([^/]+)\/consents$/.exec(path))) {
      if (profile !== m[1]) return error(404, "not_found");
      return json(200, this.consents.get(profile) ?? []);
    }
    // The typed consent switch (API-28, PRV-06, D87) for the research scopes: a new grant on a profile under 18 needs the
    // guardian's agreement (`guardian_agreed`), an adult grants their own; pause, resume and withdraw need nothing more.
    if (method === "PUT" && (m = /^\/v1\/profiles\/([^/]+)\/consents\/([^/]+)$/.exec(path))) {
      if (profile !== m[1]) return error(404, "not_found");
      const scope = decodeURIComponent(m[2]!);
      const asked = body as { action: "on" | "pause" | "withdraw"; guardian_agreed?: true };
      const list = this.consents.get(profile) ?? [];
      const was = list.find((c) => c.scope === scope) ?? consent(scope, false);
      let next: ConsentState;
      if (asked.action === "on" && was.granted) next = { ...was, paused: false, effective: true };
      else if (asked.action === "on") {
        const adult = this.adults.has(profile);
        if (!adult && asked.guardian_agreed !== true) return error(422, "validation_failed");
        next = { ...consent(scope, true), granted_by_role: adult ? "student_18_plus" : "guardian", method: adult ? "in_app_notice" : "in_app_guardian" };
      } else if (asked.action === "pause") next = { ...was, paused: true, effective: false };
      else next = consent(scope, false);
      this.consents.set(profile, [...list.filter((c) => c.scope !== scope), next]);
      this.consentSwitches.push({ scope, ...asked });
      return json(200, next);
    }
    // Exports (DAT-10): the research export with its approvals (EVL-22); the file is not written in the fake.
    if (method === "POST" && path === "/v1/exports") {
      if (profile === null) return error(401, "profile_token_expired");
      this.exports.push(body as Record<string, unknown>);
      return json(202, { job_id: `job_${ulid(this.exports.length)}`, queued_until_online: false });
    }
    if (method === "GET" && path === "/v1/telemetry/schema") return json(200, this.telemetrySchema);
    if ((method === "GET" || method === "PATCH") && (m = /^\/v1\/profiles\/([^/]+)$/.exec(path))) {
      // The profile's own record with its age band (D93): read and corrected with its own token only.
      if (profile !== m[1]) return profile === null ? error(401, "profile_token_expired") : error(404, "not_found");
      const owner = this.profiles.find((p) => p.profile_id === profile)!;
      const { age_band: band, ...change } = (method === "PATCH" ? body : {}) as Record<string, unknown>;
      if (band !== undefined) {
        if (band === "18_plus") this.adults.add(profile);
        else this.adults.delete(profile);
      }
      const about = { ...this.about.get(profile)!, ...change } as { level: "O" | "A"; subjects: string[]; exam_date: string | null };
      this.about.set(profile, about);
      return json(200, { profile_id: profile, display_name: owner.display_name, avatar: owner.avatar, ...about, age_band: this.adults.has(profile) ? "18_plus" : "13_15" });
    }
    if (method === "POST" && path === "/v1/profiles") {
      const created = body as { display_name: string; avatar: string };
      const id = `prf_${ulid(this.profiles.length + 1)}`;
      this.profiles.push({ profile_id: id, display_name: created.display_name, avatar: created.avatar, session_id: `ses_${ulid(this.profiles.length + 1)}`, canary: "" });
      this.created.push(body as Record<string, unknown>);
      this.settings.set(id, { ...this.settings.get(PROFILES[0]!.profile_id)! });
      this.notes.set(id, []);
      return json(200, { profile_id: id });
    }
    if (method === "DELETE" && (m = /^\/v1\/profiles\/([^/]+)$/.exec(path))) {
      const index = this.profiles.findIndex((p) => p.profile_id === m![1]);
      if (index >= 0) this.profiles.splice(index, 1);
      return json(200, { deleted: true });
    }
    // The subject map and the lesson player (the proposed M13.g contract additions): the unlocked profile's own.
    if (path.startsWith("/v1/curriculum/") || path.startsWith("/v1/lessons/")) {
      if (profile === null) return error(401, "profile_token_expired");
      if (method === "GET" && (m = /^\/v1\/curriculum\/([^/]+)\/map$/.exec(path))) {
        const subject = decodeURIComponent(m[1]!);
        const map = this.mapFor?.(profile, subject) ?? this.maps.get(subject);
        return map === undefined ? error(404, "not_found") : json(200, map);
      }
      const lessonMatch = /^\/v1\/lessons\/([^/]+)(\/position|\/checks)?$/.exec(path);
      const lesson = lessonMatch === null ? undefined : this.lessons.get(decodeURIComponent(lessonMatch[1]!));
      if (lessonMatch === null || lesson === undefined) return error(404, "not_found");
      const key = `${profile}:${String(lesson.lesson_id)}`;
      if (method === "GET" && lessonMatch[2] === undefined) {
        const saved = this.positions.get(key);
        const position = saved !== undefined && saved.lesson_version === lesson.version ? { block_index: saved.block_index, updated_ts: saved.updated_ts } : null;
        return json(200, { ...lesson, position });
      }
      if (method === "PUT" && lessonMatch[2] === "/position") {
        if (this.positionFails !== null) return error(503, this.positionFails);
        const asked = body as { block_index: number; lesson_version: string };
        const updated = this.now();
        this.positions.set(key, { ...asked, updated_ts: updated });
        return json(200, { lesson_id: lesson.lesson_id, block_index: asked.block_index, updated_ts: updated });
      }
      if (method === "POST" && lessonMatch[2] === "/checks") {
        const asked = body as { client_attempt_id: string; item_id: string; answer: { parts: { part_id: string }[] }; attempt?: number };
        const marked = this.mark(asked.item_id, asked.answer.parts);
        const parts = asked.answer.parts.map((p) => ({
          part_id: p.part_id, verdict: marked.verdict, marks_awarded: marked.verdict === "correct" ? 1 : 0, marks_total: 1, category: marked.category,
          misconception: null, feedback: null, check_ids: ["chk_fake"],
        }));
        // A step-shape lesson's item (D110): the why and working with a correct answer or from the second miss.
        const blocks = (lesson.blocks ?? []) as { type: string; items?: { item_id: string }[] }[];
        const block = blocks.find((b) => (b.type === "step" || b.type === "check") && (b.items ?? []).some((i) => i.item_id === asked.item_id));
        const shown = marked.verdict !== "correct" && marked.verdict !== "not_checked" && (asked.attempt ?? 1) >= 2;
        const explanation = block === undefined ? {} : {
          explanation: marked.verdict === "correct" || shown
            ? { shown, why: block.type === "step" ? "A synthetic why for this step." : null, names: null, working: [{ latex: "2 \\times 3 = 6", reason: "A synthetic line", check_id: "chk_fake" }] }
            : null,
        };
        return json(200, { client_attempt_id: asked.client_attempt_id, item_id: asked.item_id, verdict: marked.verdict, marks_awarded: parts.reduce((n, p) => n + p.marks_awarded, 0), marks_total: parts.length, parts, ...explanation });
      }
      return error(404, "not_found");
    }
    if (path.startsWith("/v1/sessions")) {
      if (profile === null) return error(401, "profile_token_expired");
      const owner = this.profiles.find((p) => p.profile_id === profile)!;
      if (method === "POST" && path === "/v1/sessions") {
        // No tutor while a mock sitting is open (AGT-24): the core answers 423 before anything else.
        if (this.mockLocked(profile)) return error(423, "tutor_locked");
        const asked = body as { subject: string; topic_id?: string | null; origin?: { kind: string; ref: string | null } };
        if (asked.origin?.kind === "exam_review") this.reviewed.push(asked.origin.ref ?? "");
        this.sessionsMade.set(owner.session_id, { subject: asked.subject, topic_id: asked.topic_id ?? null });
        return json(200, { session_id: owner.session_id, cursor: { epoch: "ep_profiles", seq: 0 } });
      }
      if (method === "GET" && path === "/v1/sessions") {
        const made = this.sessionsMade.get(owner.session_id);
        const listed = made === undefined ? [] : [{ ...snapshot(owner).session, ...made }];
        return json(200, { sessions: listed, next_before: null });
      }
      // A composer's saved draft per session and slot (INP-01): revisions count up, as the core keeps them.
      if ((m = /^\/v1\/sessions\/([^/]+)\/drafts\/([^/]+)$/.exec(path))) {
        if (m[1] !== owner.session_id) return error(404, "not_found");
        const key = `${m[1]}:${m[2]}`;
        if (method === "GET") return json(200, this.drafts.get(key) ?? { document: { type: "doc", content: [] }, revision: 0 });
        if (method === "PUT") {
          const saved = { document: (body as { document: Record<string, unknown> }).document, revision: (this.drafts.get(key)?.revision ?? 0) + 1 };
          this.drafts.set(key, saved);
          return json(200, saved);
        }
      }
      if ((m = /^\/v1\/sessions\/([^/]+)\/snapshot$/.exec(path))) {
        if (m[1] !== owner.session_id) return error(404, "not_found");
        const shown = snapshot(owner);
        return json(200, { ...shown, session: { ...shown.session, ...this.sessionsMade.get(owner.session_id) } });
      }
      if ((m = /^\/v1\/sessions\/([^/]+)\/events$/.exec(path))) {
        if (m[1] !== owner.session_id) return error(404, "not_found");
        return this.stream(init.signal ?? null);
      }
      // A turn starts (API-23): accepted and kept in `log`; the fake's tutor never answers.
      if (method === "POST" && (m = /^\/v1\/sessions\/([^/]+)\/turns$/.exec(path))) {
        if (m[1] !== owner.session_id) return error(404, "not_found");
        this.turnsStarted += 1;
        return json(202, { turn_id: `trn_${ulid(900 + this.turnsStarted)}`, message_id: `msg_${ulid(900 + this.turnsStarted)}` });
      }
    }
    if (path === "/v1/plans/current" || path === "/v1/plans" || path.startsWith("/v1/plans/") || path === "/v1/progress") {
      if (profile === null) return error(401, "profile_token_expired");
      if (path === "/v1/progress") return this.progress === null ? error(404, "not_found") : json(200, this.progress);
      if (!this.plansServed) return error(404, "not_found");
      if (method === "GET" && path === "/v1/plans/current") return json(200, this.currentPlan());
      if (method === "POST" && path === "/v1/plans") {
        const key = (body as { client_request_id?: string }).client_request_id ?? `anon${this.plans.length}`;
        const made = this.planRequests.get(key);
        if (made !== undefined) return json(200, this.plans.find((p) => p.plan_id === made));
        const plan = this.propose(this.planBlocks);
        this.planRequests.set(key, plan.plan_id);
        return json(200, plan);
      }
      return error(404, "not_found");
    }
    if (method === "GET" && path === "/v1/search/items") {
      if (profile === null) return error(401, "profile_token_expired");
      if (!this.searchServed) return error(404, "not_found");
      const q = url.searchParams.get("q") ?? "";
      this.searches.push(q);
      const words = q.toLowerCase().split(/\s+/).filter((w) => w !== "");
      const found = words.length === 0 ? [] : this.searchItems.filter((i) => i.reserved !== true && words.every((w) => i.stem.toLowerCase().includes(w)));
      return json(200, found.map(({ solution: _s, reserved: _r, ...item }) => item));
    }
    if (method === "GET" && (m = /^\/v1\/items\/([^/]+)\/solution$/.exec(path))) {
      if (profile === null) return error(401, "profile_token_expired");
      const item = this.searchItems.find((i) => i.item_id === decodeURIComponent(m![1]!));
      this.solutionsRead.push(decodeURIComponent(m[1]!));
      return item === undefined || item.reserved === true || item.solution === undefined ? error(404, "not_found") : json(200, item.solution);
    }
    // A card answer (API-14): the plan card's (`req_<plan_id>`, LRN-31) changes the plan; any other is accepted and kept
    // in `log`.
    if (method === "POST" && (m = /^\/v1\/cards\/([^/]+)\/answer$/.exec(path))) {
      if (profile === null) return error(401, "profile_token_expired");
      const plan = this.plans.find((p) => p.request_id === m![1]);
      if (plan !== undefined) return json(200, this.answerPlan(plan, (body as { answer: api_commands.CardAnswerAnswer }).answer));
      return json(200, { status: "accepted", answered_ts: 3 });
    }
    return error(404, "not_found");
  };

  // --- plans ----------------------------------------------------------------------------------------------------------

  /** The plan Home shows: the newest proposal not replaced by a change, or null. */
  currentPlan(): api_commands.PlanView | null {
    return [...this.plans].reverse().find((p) => p.status !== "changed") ?? null;
  }

  private planView(plan: Omit<api_commands.PlanView, "card" | "next_block" | "minutes">): api_commands.PlanView {
    const next = plan.status === "proposed" || plan.status === "started" ? plan.blocks.find((b) => b.status !== "done")?.index ?? null : null;
    const card: api_commands.ApiEventsCardPlan = {
      card_type: "plan", title: plan.keep_learning ? "Keep learning" : "Next up", actions: ["start", "change"],
      items: plan.blocks.map((b) => ({ id: `b${b.index}`, text: `${b.kind} (about ${b.minutes} min)`, status: b.status })),
    };
    return { ...plan, minutes: Math.max(1, plan.blocks.reduce((n, b) => n + b.minutes, 0)), next_block: next, card };
  }

  propose(blocks: FakeBlock[], replace?: Partial<api_commands.PlanView>): api_commands.PlanView {
    const id = ulid(7000 + this.plans.length).replace(/^0/, "7");
    const plan = this.planView({
      plan_id: id, request_id: `req_${id}`, date: "2026-10-17", phase: "normal", status: "proposed",
      blocks: blocks.map((b, index) => ({ index, kind: b.kind, kc_ids: b.kc_ids, minutes: b.minutes, status: "pending", done: 0, target: b.kc_ids.length, ...(b.reason_code ? { reason_code: b.reason_code } : {}) })),
      alternatives: this.planAlternatives.map((kc) => ({ kind: "main", kc_ids: [kc], minutes: 20 })),
      keep_learning: this.plans.some((p) => p.status === "done"), decided_ts: null, ...replace,
    });
    this.plans.push(plan);
    return plan;
  }

  private setPlan(plan: api_commands.PlanView, change: Partial<api_commands.PlanView>): void {
    const at = this.plans.indexOf(plan);
    this.plans[at] = this.planView({ ...plan, ...change });
  }

  private answerPlan(plan: api_commands.PlanView, answer: api_commands.CardAnswerAnswer): api_commands.CardAnswerResult {
    if (plan.status !== "proposed") return { status: "already_answered", answered_ts: 1 };
    const option = answer.option_ids?.[0];
    this.planAnswers.push(answer.skipped === true ? "skipped" : answer.action === "change" ? `change:${option ?? ""}` : answer.action ?? "");
    const blocks = plan.blocks.map((b) => ({ kind: b.kind, kc_ids: b.kc_ids, minutes: b.minutes }));
    if (answer.skipped === true) this.setPlan(plan, { status: "not_today", decided_ts: 2, alternatives: [] });
    else if (answer.action === "start") {
      this.setPlan(plan, { status: "started", decided_ts: 2, alternatives: [], blocks: plan.blocks.map((b, i) => (i === 0 ? { ...b, status: "in_progress" } : b)) });
    } else if (answer.action === "change" && option === "shorten") {
      this.setPlan(plan, { status: "changed", decided_ts: 2 });
      this.propose(blocks.slice(0, 1), { alternatives: [], keep_learning: plan.keep_learning });
    } else if (answer.action === "change" && option?.startsWith("alt_") === true) {
      const alt = plan.alternatives[Number(option.slice(4))];
      if (alt === undefined) return { status: "expired", answered_ts: null };
      this.setPlan(plan, { status: "changed", decided_ts: 2 });
      this.propose(blocks.map((b) => (b.kind === "main" ? { ...b, kc_ids: alt.kc_ids } : b)), { alternatives: [], keep_learning: plan.keep_learning });
    } else return { status: "expired", answered_ts: null };
    return { status: "accepted", answered_ts: 2 };
  }

  /** The student works through the started plan: every block done, the plan done (Keep learning comes next). */
  finishPlan(): void {
    const plan = this.currentPlan();
    if (plan === null) return;
    this.setPlan(plan, { status: "done", blocks: plan.blocks.map((b) => ({ ...b, status: "done", done: b.target })) });
  }

  /** The student stopped after the first block: it is done, the rest wait (LRN-31 stop and resume). */
  finishFirstBlock(): void {
    const plan = this.currentPlan();
    if (plan === null) return;
    this.setPlan(plan, { blocks: plan.blocks.map((b, i) => (i === 0 ? { ...b, status: "done", done: b.target } : b)) });
  }

  // --- mock exams ------------------------------------------------------------------------------------------------------

  /** Whether the profile has a sitting open: in progress, paused or interrupted (the tutor is locked, AGT-24). */
  mockLocked(profileId: string): boolean {
    return this.mockSittings.some((s) => s.profile_id === profileId && ["in_progress", "paused", "interrupted"].includes(this.tick(s).state));
  }

  /** The app was killed (or the computer lost power): every running or paused sitting is interrupted, its clock kept. */
  interruptMocks(): void {
    for (const s of this.mockSittings) {
      this.tick(s);
      if (s.state !== "in_progress" && s.state !== "paused") continue;
      s.state = "interrupted";
      s.running_since = null;
      s.pause_since = null;
      s.interruptions.push({ at: new Date(this.now()).toISOString(), remaining_ms: s.duration_ms - s.elapsed_ms });
    }
  }

  private tick(s: FakeSitting): FakeSitting {
    const now = this.now();
    if (s.state === "in_progress" && s.running_since !== null) {
      s.elapsed_ms = Math.min(s.duration_ms, s.elapsed_ms + Math.max(0, now - s.running_since));
      s.running_since = now;
      if (s.elapsed_ms >= s.duration_ms) {
        s.state = "submitted";
        s.running_since = null;
      }
    } else if (s.state === "paused" && s.pause_since !== null) {
      const last = s.pauses[s.pauses.length - 1];
      if (last !== undefined) last.length_ms = Math.max(0, now - s.pause_since);
    }
    return s;
  }

  private examOf(s: FakeSitting): Record<string, unknown> {
    this.tick(s);
    const remaining = s.duration_ms - s.elapsed_ms;
    const paper = this.mockPapers.find((p) => p.paper_id === s.paper_id);
    return {
      exam_id: s.exam_id, paper_id: s.paper_id, state: s.state, questions: this.mockQuestions, answers: s.answers, duration_ms: s.duration_ms, remaining_ms: remaining,
      pauses: s.pauses.map((p) => ({ ...p })), interruptions: s.interruptions, running_deadline_ts: s.state === "in_progress" ? this.now() + remaining : null,
      extra_time_percent: s.extra, calculator: paper?.calculator ?? false, question_ids: this.mockQuestions.map((_, i) => String(i + 1)),
    };
  }

  private report(s: FakeSitting): Record<string, unknown> {
    const ids = this.mockQuestions.map((_, i) => String(i + 1));
    const marks = (i: number) => this.mockQuestions[i]?.marks ?? 1;
    const topicOf = (i: number) => `cur.${(this.mockQuestions[i]?.kc_ids[0] ?? "kc.phy.o.motion").split(".").slice(1, 4).join(".")}`;
    const rows = ids.map((qid, i) => {
      const given = s.answers[qid]?.answer ?? null;
      const resolved = !this.mockUnresolved.includes(qid);
      const awarded = given !== null && resolved && this.mockRight(qid, given) ? marks(i) : 0;
      return { qid, i, awarded, available: resolved ? marks(i) : 0, resolved, given };
    });
    const topics = new Map<string, { topic_id: string; score: number; max_score: number }>();
    for (const r of rows) {
      const topic = topics.get(topicOf(r.i)) ?? { topic_id: topicOf(r.i), score: 0, max_score: 0 };
      topic.score += r.awarded;
      topic.max_score += r.available;
      topics.set(topic.topic_id, topic);
    }
    const score = rows.reduce((n, r) => n + r.awarded, 0);
    const max = rows.reduce((n, r) => n + r.available, 0);
    return {
      exam_id: s.exam_id, score, max_score: max, by_topic: [...topics.values()],
      review_items: rows.map((r) => ({ question_id: r.qid, correct: r.resolved && r.awarded === marks(r.i), show_me_why_ref: `${s.exam_id.slice(4)}:${r.qid}` })),
      criteria: rows.map((r) => ({ question_id: r.qid, criteria: [{
        criterion_id: "B1", mark_type: "B", awarded: r.awarded, available: r.resolved ? marks(r.i) : 0, resolved: r.resolved,
        scheme: r.resolved ? "The answer" : "A synthetic mark-scheme point to compare with.", notice_key: r.resolved ? null : "assessment.not_marked_automatically",
      }] })),
      flagged: ids.filter((q) => s.answers[q]?.flagged === true), unanswered: rows.filter((r) => r.given === null).map((r) => r.qid),
      integrity_counts: { focus_loss: this.mockSignals.filter((x) => x.kind === "focus_loss" && x.amount > 30_000).length, large_paste: this.mockSignals.filter((x) => x.kind === "large_paste" && x.amount > 200).length },
      extra_time_percent: s.extra, taken_with_extra_time: s.extra > 0, pauses: s.pauses, interruptions: s.interruptions, time_by_section: { A: s.elapsed_ms },
      marks_lost: { M: 0, A: 0, B: max - score }, practice_kc_ids: [...new Set(rows.filter((r) => r.awarded < marks(r.i)).flatMap((r) => this.mockQuestions[r.i]?.kc_ids ?? []))].slice(0, 3), optional_omitted: [],
      practice_set_ref: `set_${ulid(71)}`, grade_band: this.mockBand,
    };
  }

  private mocks(method: string, path: string, body: unknown, profile: string | null): Response {
    if (profile === null) return error(401, "profile_token_expired");
    const mine = this.mockSittings.filter((s) => s.profile_id === profile);
    if (method === "GET" && path === "/v1/mocks") {
      if (!this.mocksServed) return error(404, "not_found");
      const sittings = [...mine].reverse().map((s) => {
        this.tick(s);
        const report = s.result as { score?: number; max_score?: number } | null;
        return { exam_id: s.exam_id, paper_id: s.paper_id, state: s.state, remaining_ms: s.duration_ms - s.elapsed_ms, score: report?.score ?? null, max_score: report?.max_score ?? null };
      });
      return json(200, { papers: this.mockPapers, sittings });
    }
    if (method === "POST" && path === "/v1/mocks") {
      const paper = this.mockPapers.find((p) => p.paper_id === (body as { paper_id: string }).paper_id);
      if (paper === undefined) return error(404, "not_found");
      const extra = (this.settings.get(profile)?.extra_time_percent ?? 0) as 0 | 25 | 50;
      const sitting: FakeSitting = {
        exam_id: `exm_${ulid(500 + this.mockSittings.length)}`, paper_id: paper.paper_id, profile_id: profile, state: "ready",
        duration_ms: paper.duration_minutes * 60_000 * (100 + extra) / 100, extra, elapsed_ms: 0, running_since: null, pause_since: null, pauses: [], interruptions: [], answers: {}, result: null,
      };
      this.mockSittings.push(sitting);
      return json(200, this.examOf(sitting));
    }
    const m = /^\/v1\/mocks\/([^/]+)(?:\/(start|pause|resume|submit|navigate|integrity)|\/answers\/([^/]+))?$/.exec(path);
    const s = m === null ? undefined : mine.find((x) => x.exam_id === decodeURIComponent(m[1]!));
    if (m === null || s === undefined) return error(404, "not_found");
    this.tick(s);
    const action = m[2];
    const now = this.now();
    if (method === "GET" && action === undefined && m[3] === undefined) return json(200, this.examOf(s));
    if (method === "PUT" && m[3] !== undefined) {
      if (s.state !== "in_progress") return error(422, "validation_failed", { details: { reason: "answers_locked" } });
      s.answers[decodeURIComponent(m[3])] = body as { answer: unknown; flagged: boolean };
      return json(200, { saved_ts: now });
    }
    if (method !== "POST") return error(404, "not_found");
    if (action === "start" && s.state === "ready") {
      s.state = "in_progress";
      s.running_since = now;
    } else if (action === "pause" && s.state === "in_progress") {
      if (s.pauses.length >= 2) return error(422, "validation_failed", { details: { reason: "pause_budget_exhausted" } });
      s.state = "paused";
      s.running_since = null;
      s.pause_since = now;
      s.pauses.push({ at: new Date(now).toISOString(), length_ms: 0 });
    } else if (action === "resume" && (s.state === "paused" || s.state === "interrupted")) {
      s.state = "in_progress";
      s.running_since = now;
      s.pause_since = null;
    } else if (action === "navigate") {
      return json(200, { saved_ts: now });
    } else if (action === "integrity") {
      this.mockSignals.push(body as { kind: string; amount: number });
      return json(200, { recorded: true });
    } else if (action === "submit") {
      if (["in_progress", "paused", "interrupted", "submitted"].includes(s.state)) {
        s.state = "marked";
        s.running_since = null;
        s.result = this.report(s);
        const weak = (s.result as { practice_kc_ids: string[] }).practice_kc_ids;
        if (weak.length) this.propose([{ kind: "main", kc_ids: weak, minutes: 20, reason_code: "mock_follow_up" }]);
      }
      return s.result === null ? error(422, "validation_failed") : json(200, s.result);
    } else {
      return error(422, "validation_failed", { details: { reason: "invalid_transition" } });
    }
    return json(200, this.examOf(s));
  }

  /** A live stream that says hello and then stays open (heartbeats only) until the client aborts it. */
  private stream(signal: AbortSignal | null): Response {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start: (controller) => {
        this.openStreams += 1;
        controller.enqueue(encoder.encode(`event: control\ndata: ${JSON.stringify({ type: "stream.hello", replayed: 0 })}\n\n`));
        let open = true;
        const end = () => {
          if (!open) return;
          open = false;
          this.openStreams -= 1;
          this.streamEnds.delete(end);
          try {
            controller.close();
          } catch {
            /* already closed */
          }
        };
        this.streamEnds.add(end);
        signal?.addEventListener("abort", () => {
          if (!open) return;
          open = false;
          this.openStreams -= 1;
          this.streamEnds.delete(end);
          try {
            controller.error(new DOMException("aborted", "AbortError"));
          } catch {
            /* already closed */
          }
        });
      },
    });
    return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
  }
}
