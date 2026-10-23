// "What the tutor knows about you" (LRN-36, UXS-28, MEM-09, MEM-14, MEM-27, LRN-37, PRV-10, PRV-11): the learner record
// in plain words, from the core's learner view. The sections follow LRN-36's order: the level and subjects, what is
// going well and what is being worked on (as words, never a score), the mistakes being watched (each can be called
// not accurate), the ways of learning (each can be set, or left to the tutor), and the notes, with the notes the
// tutor needs a decision on first: a new note that disagrees with an older one, or a change to a note that is the
// student's. A note the core keeps out of every prompt is marked, so it can be removed. The plan reason and
// learning-record inventory come from the same profile's durable projections. No probability or score is ever shown. Note text is rendered as text, never as markup (MEM-27).
import { useEffect, useSyncExternalStore } from "react";
import {
  PREFERENCE_KEYS, PREFERENCE_VALUES, type ForgetReason, type KnowsController, type KnowsKc, type KnowsNote, type KnowsReview, type KnowsView,
  type PreferenceKey, type Sharing,
} from "@jana/client-core";
import { Icon } from "../icons.js";
import { useT } from "../i18n.js";
import { Button, EmptyState, ErrorState, Notice, Skeleton } from "../primitives/index.js";

export type { ForgetReason } from "@jana/client-core";

/** The page's sections, in the order LRN-36 lists them. */
export const KNOWS_SECTIONS = ["about", "going_well", "working_on", "mistakes", "preferences", "notes", "plan", "records"] as const;
export type KnowsSection = (typeof KNOWS_SECTIONS)[number];

/** Sections whose data the core cannot serve yet: shown as not available, never as empty. */
export const NOT_YET_AVAILABLE: ReadonlySet<KnowsSection> = new Set();

/** The sharing lines for the consent state: private unless a consent is in effect, and then exactly what is shared. */
export function sharingLines(sharing: Sharing | null): string[] {
  if (sharing === null) return ["unknown"];
  const on = (["backup", "devices", "parent_view", "cloud_tutor"] as const).filter((flag) => sharing[flag]);
  return [...(on.length === 0 ? ["private"] : on), "settings"];
}

export interface KnowsActions {
  onForget: (noteId: string, reason: ForgetReason) => void;
  onResolve?: (reviewId: string, accept: boolean) => void;
  onDisputeMistake?: (misconceptionId: string) => void;
  onSetPreference?: (key: PreferenceKey, value: string | boolean | null) => void;
}

const field = "min-h-8 rounded-control border border-line-strong bg-canvas px-3 text-body text-ink";

function About({ view }: { view: KnowsView }) {
  const t = useT();
  if (view.about === null) return <EmptyState message={t("knows.about.unavailable")} />;
  const subject = (s: string) => {
    const key = `settings.profiles.subject.${s}`;
    const name = t(`settings.profiles.subject.${s}`);
    return name === key ? s : name;
  };
  const rows: [string, string][] = [
    [t("knows.about.level"), t(`settings.profiles.level_name.${view.about.level.toLowerCase()}`)],
    [t("knows.about.subjects"), view.about.subjects.map(subject).join(", ")],
  ];
  if (view.about.exam_date !== null) rows.push([t("knows.about.exam"), view.about.exam_date]);
  return (
    <dl className="flex flex-col gap-1 text-ui">
      {rows.map(([label, value]) => (
        <div key={label} className="flex gap-4">
          <dt className="min-w-24 text-muted">{label}</dt>
          <dd className="text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** KCs in one band, each as its statement and its state in words. */
function Kcs({ kcs, empty }: { kcs: KnowsKc[]; empty: string }) {
  const t = useT();
  if (kcs.length === 0) return <EmptyState message={empty} />;
  return (
    <ul className="flex flex-col gap-1 text-body text-ink">
      {kcs.map((kc) => (
        <li key={kc.kc_id} data-kc-id={kc.kc_id}>
          {kc.statement} <span className="text-meta text-muted">· {t(`knows.state.${kc.state}`)}</span>
        </li>
      ))}
    </ul>
  );
}

function Mistakes({ view, onDispute }: { view: KnowsView; onDispute?: ((id: string) => void) | undefined }) {
  const t = useT();
  if (view.misconceptions.length === 0) return <EmptyState message={t("knows.mistakes.empty")} />;
  return (
    <ul className="flex flex-col">
      {view.misconceptions.map((m) => (
        <li key={m.misconception_id} className="flex flex-wrap items-center gap-2 border-b border-line py-2" data-misconception-id={m.misconception_id}>
          <span className="flex-1 text-body text-ink">
            {m.name}
            {m.status === "resolving" && <span className="text-meta text-muted"> · {t("knows.mistakes.resolving")}</span>}
          </span>
          {onDispute !== undefined && <Button onClick={() => onDispute(m.misconception_id)}>{t("knows.notes.not_right")}</Button>}
        </li>
      ))}
    </ul>
  );
}

function Preferences({ view, onSet }: { view: KnowsView; onSet?: KnowsActions["onSetPreference"] }) {
  const t = useT();
  return (
    <div className="flex flex-col gap-2">
      {PREFERENCE_KEYS.map((key) => {
        const current = view.preferences.find((p) => p.key === key);
        const chosen = current?.source === "override" ? String(current.value) : "";
        return (
          <label key={key} className="flex flex-wrap items-center gap-3 text-ui text-ink" data-preference={key}>
            <span className="min-w-48">{t(`knows.preferences.key.${key}`)}</span>
            <select
              className={field}
              value={chosen}
              disabled={onSet === undefined}
              onChange={(event) => {
                const raw = event.target.value;
                const value = raw === "" ? null : (PREFERENCE_VALUES[key] as readonly (string | boolean)[]).find((v) => String(v) === raw) ?? null;
                onSet?.(key, value);
              }}
            >
              <option value="">{t("knows.preferences.tutor_decides")}</option>
              {(PREFERENCE_VALUES[key] as readonly (string | boolean)[]).map((v) => (
                <option key={String(v)} value={String(v)}>{t(`knows.preferences.value.${key}.${String(v)}`)}</option>
              ))}
            </select>
          </label>
        );
      })}
    </div>
  );
}

function Quoted({ label, note }: { label: string; note: KnowsNote }) {
  return (
    <p className="text-body text-ink">
      <span className="text-meta text-muted">{label} </span>
      {note.text}
    </p>
  );
}

/** One decision the tutor needs (MEM-09): the question, the note text it is about, and its two answers. */
function Review({ item, changed, onResolve }: { item: KnowsReview; changed: boolean; onResolve?: KnowsActions["onResolve"] }) {
  const t = useT();
  const kind = item.kind === "drop" ? "drop" : item.target === null ? "add" : "replace";
  return (
    <li className="flex flex-col gap-2 rounded-card border border-line-strong p-3" data-review-id={item.review_id} data-review-kind={kind}>
      {changed && <Notice message={t("knows.reviews.changed")} />}
      <p className="text-ui font-semibold text-ink">{t(`knows.reviews.question.${kind}`)}</p>
      {item.target !== null && <Quoted label={t(kind === "replace" ? "knows.reviews.older" : "knows.reviews.yours")} note={item.target} />}
      {item.pending !== null && <Quoted label={t("knows.reviews.newer")} note={item.pending} />}
      {onResolve !== undefined && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onResolve(item.review_id, true)}>{t(`knows.reviews.accept.${kind}`)}</Button>
          <Button onClick={() => onResolve(item.review_id, false)}>{t(`knows.reviews.reject.${kind}`)}</Button>
        </div>
      )}
    </li>
  );
}

function Note({ note, onForget }: { note: KnowsNote; onForget: KnowsActions["onForget"] }) {
  const t = useT();
  return (
    <li className="flex flex-col gap-1 border-b border-line py-2" data-note-id={note.note_id} data-flagged={note.flagged}>
      <p className="text-body text-ink">{note.text}</p>
      {note.flagged && (
        <p className="flex items-center gap-1 text-meta text-warn">
          <Icon name="warning" />
          {t("knows.notes.flagged")}
        </p>
      )}
      <p className="text-meta text-muted">
        {t("knows.notes.saved_on", { date: note.updated_ts })}
        {note.source === "student" && <> · {t("knows.notes.you_asked")}</>}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => onForget(note.note_id, "not_right")}>{t("knows.notes.not_right")}</Button>
        <Button onClick={() => onForget(note.note_id, "forget")}>{t("knows.notes.forget")}</Button>
      </div>
    </li>
  );
}

function Notes({ view, actions }: { view: KnowsView; actions: KnowsActions }) {
  const t = useT();
  return (
    <div className="flex flex-col gap-3">
      {view.reviews.length > 0 && (
        <div className="flex flex-col gap-2" data-reviews>
          <h3 className="text-ui font-semibold text-ink">{t("knows.reviews.title")}</h3>
          <ul className="flex flex-col gap-2">
            {view.reviews.map((item) => <Review key={item.review_id} item={item} changed={view.changed === item.review_id} onResolve={actions.onResolve} />)}
          </ul>
        </div>
      )}
      {view.notes.length === 0 ? (
        <EmptyState message={t("knows.notes.empty")} />
      ) : (
        <ul className="flex flex-col">
          {view.notes.map((note) => <Note key={note.note_id} note={note} onForget={actions.onForget} />)}
        </ul>
      )}
    </div>
  );
}

/** The page from its view: the gallery and the tests render this directly. */
export function KnowsContent({ view, onRetry, onOpenSettings, onClose, ...actions }: KnowsActions & {
  view: KnowsView;
  onRetry?: () => void;
  onOpenSettings?: () => void;
  onClose?: () => void;
}) {
  const t = useT();
  const loading = view.status === "idle" || view.status === "loading";
  const section = (id: KnowsSection) => {
    if (NOT_YET_AVAILABLE.has(id)) return <EmptyState message={t("knows.not_yet_available")} />;
    switch (id) {
      case "about":
        return <About view={view} />;
      case "going_well":
        return <Kcs kcs={view.kcs.filter((k) => k.band === "secure")} empty={t("knows.going_well.empty")} />;
      case "working_on":
        return <Kcs kcs={view.kcs.filter((k) => k.band === "learning")} empty={t("knows.working_on.empty")} />;
      case "mistakes":
        return <Mistakes view={view} onDispute={actions.onDisputeMistake} />;
      case "preferences":
        return <Preferences view={view} {...(actions.onSetPreference !== undefined ? { onSet: actions.onSetPreference } : {})} />;
      case "plan":
        return <p className="text-body text-ink">{t(view.plan_reason ? `knows.plan.${view.plan_reason}` : "knows.plan.empty")}</p>;
      case "records":
        return (view.records?.length ?? 0) === 0 ? <EmptyState message={t("knows.records.empty")} /> : (
          <ul className="flex flex-col gap-1 text-body text-ink">
            {view.records?.map((record) => <li key={record.kind} data-record-kind={record.kind}>{t(`knows.records.${record.kind}`)}: {record.count}</li>)}
          </ul>
        );
      default:
        return <Notes view={view} actions={actions} />;
    }
  };
  return (
    <div className="flex flex-col gap-6 p-6" data-knows-status={view.status}>
      <div className="flex items-center justify-between">
        <h1 className="text-heading font-semibold text-ink">{t("knows.title")}</h1>
        {onClose !== undefined && <Button onClick={onClose}>{t("action.back")}</Button>}
      </div>
      <section aria-labelledby="knows-sharing" className="flex items-start gap-2 text-ui text-ink">
        <Icon name="on-this-computer" />
        <div className="flex flex-col gap-1">
          <h2 id="knows-sharing" className="text-ui font-semibold">{t("knows.sharing.title")}</h2>
          {sharingLines(view.status === "ready" ? view.sharing : null).map((line) => (
            <p key={line} data-sharing={line}>{t(`knows.sharing.${line}`)}</p>
          ))}
        </div>
      </section>
      {view.memory_saving === false && (
        <Notice message={t("knows.saving_off")} {...(onOpenSettings !== undefined ? { action: { label: t("app.settings"), onClick: onOpenSettings } } : {})} />
      )}
      {view.forgotten !== null && <Notice message={t("knows.notes.forgotten")} />}
      {view.error !== null && <ErrorState message={t(view.errorOn === "note" ? "knows.notes.forget_failed" : "knows.correction_failed")} />}
      {view.status === "failed" ? (
        <ErrorState message={t("knows.unavailable")} {...(onRetry !== undefined ? { action: { label: t("action.try_again"), onClick: onRetry } } : {})} />
      ) : (
        KNOWS_SECTIONS.map((id) => (
          <section key={id} aria-labelledby={`knows-${id}`} className="flex flex-col gap-2" data-section={id}>
            <h2 id={`knows-${id}`} className="text-ui font-semibold text-ink">{t(`knows.section.${id}`)}</h2>
            {loading ? <Skeleton lines={2} /> : section(id)}
          </section>
        ))
      )}
    </div>
  );
}

/** The page for the unlocked profile: reads on open, forgets and corrects through the controller. */
export function KnowsPage({ knows, onClose, onOpenSettings }: { knows: KnowsController; onClose?: () => void; onOpenSettings?: () => void }) {
  const view = useSyncExternalStore(knows.subscribe, knows.getView, knows.getView);
  useEffect(() => {
    knows.load().catch(() => undefined); // a locked profile reads nothing; the app shows the picker
  }, [knows]);
  const retry = () => void knows.load().catch(() => undefined);
  return (
    <KnowsContent
      view={view}
      onForget={(noteId, reason) => void knows.forget(noteId, reason).catch(() => undefined)}
      onResolve={(reviewId, accept) => void knows.resolveReview(reviewId, accept).catch(() => undefined)}
      onDisputeMistake={(id) => void knows.disputeMisconception(id).catch(() => undefined)}
      onSetPreference={(key, value) => void knows.setPreference(key, value).catch(() => undefined)}
      onRetry={retry}
      {...(onOpenSettings !== undefined ? { onOpenSettings } : {})}
      {...(onClose !== undefined ? { onClose } : {})}
    />
  );
}
