// Home (UXS-12, UXS-67; direction A "Studio"): it tells the student what to do next. "Ready to learn, {name}?" in
// display type leads to the one input (UXS-67, D117): four ways to add material above it (Upload, Link, Paste,
// Record, each opening the study area) and one box that takes a problem, a question or a request. What happens next is
// chosen by the content: a problem in an installed subject opens the tutor, material the study area, any other
// question Ask anything, whose answer shows here under the box. The subjects sit beside it as chips; then the study
// plan, "Next up" (LRN-28 to LRN-33): the next activity first with Start, Change and Not today; then two cards, "Pick
// up where you left off" (the newest sessions, each reopening where it was left, UXS-19) and today's practice, the
// ideas the learner model says are due, each with its mastery word (DSN-23). Where no tutor answers here, the box
// gives way to worked-solution search (UXS-51, PLT-29). The header carries the gentle daily goal chip (LRN-45).
import { useEffect, useRef, type ChangeEvent, type ReactNode } from "react";
import { CLIENT_KEYS, type DueIdea, type SessionGroup } from "@jana/client-core";
import { ScreenHeader } from "../frame/Frame.js";
import { useT } from "../i18n.js";
import { Icon, type IconName } from "../icons.js";
import { MasteryMark } from "../learn/Mastery.js";
import { SubjectDot, SuggestionChip } from "../primitives/index.js";

export interface HomeSubject {
  subjectId: string;
  subject: string;
  label: string;
  chosen: boolean;
}

export interface HomePickup {
  sessionId: string;
  title: string;
  subject: string;
  subjectLabel: string;
  day: SessionGroup;
}

/** The greeting's part of the day, by the computer's local hour. */
export function partOfDay(hour: number): "morning" | "afternoon" | "evening" {
  if (hour >= CLIENT_KEYS.ui_greeting_evening_hour) return "evening";
  return hour >= CLIENT_KEYS.ui_greeting_afternoon_hour ? "afternoon" : "morning";
}

function Row({ icon, name, meta, subject, onClick, children }: { icon: IconName; name: string; meta: string; subject: string; onClick: () => void; children?: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="jana-press flex min-h-11 w-full items-start gap-3 rounded-control px-2 py-3 text-start text-ink hover:bg-wash">
      <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-control bg-panel text-muted"><Icon name={icon} /></span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-ui font-medium">{name}</span>
        <span className="flex items-center gap-1.5 text-meta text-faint"><SubjectDot subject={subject} />{meta}</span>
        {children}
      </span>
      <span aria-hidden="true" className="self-center text-faint"><Icon name="expand" size={16} /></span>
    </button>
  );
}

/** The four ways to add material above the box (UXS-67); each opens the study area. */
export interface HomeMaterials {
  onUpload: (file: File) => void;
  onLink: () => void;
  onPaste: () => void;
  onRecord: (file: File) => void;
}

/** Accepted on Home's Upload: what the study area reads (STU-02). Record takes a recording the student holds. */
const UPLOAD_ACCEPT = ".pdf,.docx,.pptx,.txt,.md,.png,.jpg,.jpeg,.webp,application/pdf,text/plain,text/markdown,image/png,image/jpeg,image/webp";
const RECORDING_ACCEPT = ".mp3,.m4a,.wav,.ogg,.webm,audio/*";

function Materials({ materials }: { materials: HomeMaterials }) {
  const t = useT();
  const upload = useRef<HTMLInputElement>(null), record = useRef<HTMLInputElement>(null);
  const picked = (pick: (file: File) => void) => (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) pick(file);
  };
  return (
    <div role="group" aria-label={t("home.add_material")} data-home-materials="" className="flex flex-wrap gap-2">
      <SuggestionChip icon="study" onClick={() => upload.current?.click()}>{t("home.material.upload")}</SuggestionChip>
      <SuggestionChip icon="share" onClick={materials.onLink}>{t("home.material.link")}</SuggestionChip>
      <SuggestionChip icon="notes" onClick={materials.onPaste}>{t("home.material.paste")}</SuggestionChip>
      <SuggestionChip icon="voice" onClick={() => record.current?.click()}>{t("home.material.record")}</SuggestionChip>
      <input ref={upload} type="file" tabIndex={-1} aria-hidden="true" accept={UPLOAD_ACCEPT} onChange={picked(materials.onUpload)} className="sr-only" />
      <input ref={record} type="file" tabIndex={-1} aria-hidden="true" accept={RECORDING_ACCEPT} onChange={picked(materials.onRecord)} className="sr-only" />
    </div>
  );
}

export function Home({ name, ask, materials, answer, notice, plan, countdown, goal, mock, subjects, onSubject, pickup, onPickup, practice, onPractice }: {
  name: string;
  /** The one box (the composer, inline), or null where no tutor answers here. */
  ask: ReactNode | null;
  /** The four ways to add material, or null where the study area is not available. */
  materials?: HomeMaterials | null;
  /** Ask anything's answer to the box's last general question (STU-20). */
  answer?: ReactNode;
  /** What still works where no tutor answers (PLT-29), or why the tutor waits while a mock exam is open (AGT-24). */
  notice?: ReactNode;
  /** The study plan card (UXS-12): "Next up". */
  plan?: ReactNode;
  /** The daily goal chip in the header (LRN-45), absent when the learner hid it. */
  goal?: ReactNode;
  /** The countdown to the nearest exam date and any reminder due (LRN-44), above the plan. */
  countdown?: ReactNode;
  /** A mock exam card: one closed after the abandonment window, with "Start a new mock" (TABLE UXS-25a). */
  mock?: ReactNode;
  subjects: HomeSubject[];
  onSubject: (subjectId: string) => void;
  pickup: HomePickup[];
  onPickup: (sessionId: string) => void;
  practice: { ideas: DueIdea[]; refreshes: number; subjectLabel: (subject: string) => string };
  onPractice: (idea: DueIdea) => void;
}) {
  const t = useT();
  const shownPickup = pickup.slice(0, CLIENT_KEYS.ui_home_pickup_max);
  // Arriving with focus nowhere (the picker or first run that had it is gone) puts it on the greeting, so a keyboard
  // or screen-reader user starts on this screen instead of at the top of the page.
  const greeting = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (document.activeElement === null || document.activeElement === document.body) greeting.current?.focus();
  }, []);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <ScreenHeader {...(goal !== undefined ? { end: goal } : {})} />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-10 pb-12">
        <div className="mx-auto flex w-full max-w-(--layout-composerMax) flex-col gap-12">
          <section aria-labelledby="home-greeting" className="flex flex-col gap-5">
            <div className="flex flex-col gap-1 px-1">
              <h1 id="home-greeting" ref={greeting} tabIndex={-1} className="text-display">{t("home.ready", { name })}</h1>
            </div>
            {/* One input leads (UXS-67): the ways to add material above the box, then the box itself. */}
            {ask !== null && materials != null && <Materials materials={materials} />}
            {ask !== null && <>
              <h2 className="sr-only">{t("home.ask")}</h2>
              {ask}
            </>}
            {answer}
            {notice}
            {countdown}
            {plan}
            {subjects.length > 1 && (
              <div role="group" aria-label={t("home.subjects")} className="flex flex-wrap gap-2">
                {subjects.map((s) => (
                  <SuggestionChip key={s.subjectId} aria-pressed={s.chosen} onClick={() => onSubject(s.subjectId)}>
                    <SubjectDot subject={s.subject} />
                    {s.label}
                  </SuggestionChip>
                ))}
              </div>
            )}
          </section>
          {mock}
          {(shownPickup.length > 0 || practice.ideas.length > 0) && (
            <div className="flex flex-wrap items-start gap-4">
              {shownPickup.length > 0 && (
                <section aria-labelledby="home-pickup" className="flex min-w-72 flex-1 flex-col gap-2 rounded-card border border-line bg-canvas px-3 pt-5 pb-3">
                  <h2 id="home-pickup" className="px-2 text-heading">{t("home.pickup")}</h2>
                  <ul className="flex flex-col divide-y divide-line">
                    {shownPickup.map((p) => (
                      <li key={p.sessionId} data-pickup={p.sessionId}>
                        <Row icon="tutor" name={p.title} meta={t("home.pickup_meta", { subject: p.subjectLabel, day: t(`frame.group.${p.day}`) })} subject={p.subject} onClick={() => onPickup(p.sessionId)} />
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {practice.ideas.length > 0 && (
                <section aria-labelledby="home-practice" className="flex min-w-72 flex-1 flex-col gap-3 rounded-card border border-line bg-canvas px-3 pt-5 pb-3">
                  <div className="flex flex-col gap-0.5 px-2">
                    <h2 id="home-practice" className="text-heading">{t("home.practice")}</h2>
                    {practice.refreshes > 0 && <p className="text-meta text-faint">{t("home.practice_due", { count: practice.refreshes })}</p>}
                  </div>
                  <ul className="flex flex-col gap-1">
                    {practice.ideas.map((idea) => (
                      <li key={idea.kc.kc_id} data-due-kc={idea.kc.kc_id}>
                        <button type="button" onClick={() => onPractice(idea)} className="jana-press flex min-h-11 w-full items-center justify-between gap-3 rounded-control px-2 py-2 text-start hover:bg-wash">
                          <span className="flex min-w-0 flex-col">
                            <span className="text-ui font-medium text-ink">{idea.kc.statement}</span>
                            <span className="text-meta text-faint">{practice.subjectLabel(idea.subject)}</span>
                          </span>
                          <MasteryMark state={idea.kc.state} />
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
