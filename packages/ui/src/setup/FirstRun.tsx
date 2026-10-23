// First run's one step, "Who's learning?" (UXS-10 step 1, TABLE PLT-17a, D84, D86; direction A "Studio"): on paper
// with the lockup (DSN-25), a first name or nickname, with "Add another student" for more, the line that everything stays
// on this computer, and "Start learning". Nothing else is asked: no PIN, code, licence or account; age band, level,
// subjects and the tutor model take TABLE PLT-17b's defaults, the subjects from the packs installed on this computer.
// Each student is added through `POST /v1/profiles`; the first one opens and the hand-off follows. Names already added
// stay added if a later one fails, and are not added twice when "Start learning" is pressed again. Quitting part way
// resumes here on the next launch with the students already added shown (`existing`, UXS-10).
import { useEffect, useId, useRef, useState } from "react";
import { firstRunProfile, type ProfileController } from "@jana/client-core";
import type { PackList } from "@jana/contracts-ts";
import { useT } from "../i18n.js";
import { Icon } from "../icons.js";
import { Button, ErrorState, FIELD_LOOK } from "../primitives/index.js";
import { Avatar, discOf } from "../profiles/Avatar.js";
import { WelcomeCard } from "./Welcome.js";

export function FirstRun({ profiles, packs, existing = [], onStarted, onRestore }: {
  profiles: ProfileController;
  /** The installed packs (`GET /v1/packs`): the new students' subjects and level. */
  packs: PackList["packs"];
  /** Students added before first run was left part way (UXS-10 resume): shown, not added again. */
  existing?: readonly { profileId: string; name: string; avatar: string }[];
  /** The first student was added and opened: the hand-off follows. */
  onStarted: (name: string) => void;
  onRestore?: () => void;
}) {
  const t = useT();
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const [names, setNames] = useState<string[]>(existing.length > 0 ? [] : [""]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const added = useRef(new Map<number, string>()); // field index -> the profile made from it
  useEffect(() => heading.current?.focus(), []);
  const filled = names.map((n) => n.trim()).filter((n) => n !== "");
  const start = async () => {
    setPending(true);
    setError(null);
    try {
      for (const [index, name] of names.entries()) {
        if (name.trim() === "" || added.current.has(index)) continue;
        const created = await profiles.family.addProfile(firstRunProfile(name, packs, existing.length + added.current.size));
        added.current.set(index, created.profile_id);
      }
      const first = names.findIndex((n) => n.trim() !== "");
      const opening = existing[0] !== undefined ? { id: existing[0].profileId, name: existing[0].name } : { id: added.current.get(first), name: (names[first] ?? "").trim() };
      if (opening.id === undefined || !(await profiles.unlock(opening.id))) throw new Error("open_failed");
      onStarted(opening.name);
    } catch (failure) {
      setError((failure as { code?: string }).code ?? "internal_error");
    } finally {
      setPending(false);
    }
  };
  return (
    <WelcomeCard brand labelledBy={id} data-first-run-step="who">
      <div className="flex flex-col gap-2">
        <h1 id={id} ref={heading} tabIndex={-1} className="text-display">{t("first_run.title")}</h1>
        <p className="text-body text-muted">{t("first_run.privacy")}</p>
      </div>
      {existing.length > 0 && (
        <ul aria-label={t("first_run.added")} className="flex flex-wrap justify-center gap-2" data-first-run-existing="">
          {existing.map((p, order) => (
            <li key={p.profileId} className="flex min-w-26 flex-col items-center gap-2 rounded-card px-2 py-3 text-ui font-medium">
              <Avatar name={p.name} disc={discOf(p.avatar, order)} size="xl" />
              {p.name}
            </li>
          ))}
        </ul>
      )}
      <form aria-labelledby={id} className="flex w-full flex-col gap-4 text-start"
        onSubmit={(event) => {
          event.preventDefault();
          if (!pending && (filled.length > 0 || existing.length > 0)) void start();
        }}>
        {names.map((name, index) => (
          <label key={index} className="flex flex-col gap-1.5 text-meta font-medium text-muted">
            {index === 0 && existing.length === 0 ? t("first_run.name") : t("first_run.another_name")}
            <input className={FIELD_LOOK} autoComplete="off" maxLength={40} value={name} disabled={added.current.has(index)}
              autoFocus={index > 0 || existing.length > 0} onChange={(event) => setNames((all) => all.map((n, i) => (i === index ? event.target.value : n)))} />
          </label>
        ))}
        <div>
          <Button tone="ghost" disabled={pending} onClick={() => setNames((all) => [...all, ""])}><Icon name="add-student" size={16} />{t("first_run.add_another")}</Button>
        </div>
        <Button type="submit" tone="primary" disabled={pending || (filled.length === 0 && existing.length === 0)}>{t("first_run.start")}<Icon name="go-next" size={16} /></Button>
        {error !== null && <ErrorState message={t(`error.${error === "open_failed" ? "internal_error" : error}`)} />}
      </form>
      {onRestore !== undefined && <Button tone="ghost" disabled={pending} onClick={onRestore}>{t("recovery.restore")}</Button>}
    </WelcomeCard>
  );
}
