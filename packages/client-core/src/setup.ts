// The subjects on this computer and first run's defaults (UXS-10, UXS-22, PLT-17, TABLE PLT-17b). The core lists each
// installed pack with its subject as the pack names it (the curriculum code, `phy`, CUR-02); profiles and sessions name
// subjects in full (`physics`). Nothing here is hard-coded per computer: the subjects come from the installed packs.
import type { CreateProfile, PackList } from "@jana/contracts-ts";

/** Profile subject names and their curriculum codes (CUR-02), in the order subjects are listed. */
export const SUBJECT_CODES = { mathematics: "mth", physics: "phy", chemistry: "chm", biology: "bio", accounting: "acc" } as const;
export type SubjectName = keyof typeof SUBJECT_CODES;
export const SUBJECT_NAMES = Object.keys(SUBJECT_CODES) as SubjectName[];

/** The profile subject name for a pack's or session's subject, given as its code or its name; null when unknown. */
export function subjectName(subject: string): SubjectName | null {
  if (subject in SUBJECT_CODES) return subject as SubjectName;
  return SUBJECT_NAMES.find((name) => SUBJECT_CODES[name] === subject) ?? null;
}

export interface InstalledSubject {
  subject: SubjectName;
  level: "O" | "A";
  /** The curriculum map's subject node id (`cur.phy.o`). */
  subjectId: string;
}

/** The installed subjects, one per subject and level, in the order of SUBJECT_NAMES (O level first). A pack that failed
 * verification is still listed: the map and the tutor say it is switched off (ARC-26). */
export function installedSubjects(packs: PackList["packs"]): InstalledSubject[] {
  const found = new Map<string, InstalledSubject>();
  for (const pack of packs) {
    const subject = subjectName(pack.subject);
    if (subject === null) continue;
    const subjectId = `cur.${SUBJECT_CODES[subject]}.${pack.level.toLowerCase()}`;
    found.set(subjectId, { subject, level: pack.level, subjectId });
  }
  const rank = (s: InstalledSubject) => SUBJECT_NAMES.indexOf(s.subject) * 2 + (s.level === "O" ? 0 : 1);
  return [...found.values()].sort((a, b) => rank(a) - rank(b));
}

/** A new student as first run adds them (TABLE PLT-17b): the name is the only thing asked; the age band is the minor
 * band "13 to 15"; level and subjects are every installed subject at the level of the installed packs (O level when
 * both are installed). With no pack installed yet, every subject at O level, so content added later fits. The disc
 * follows the order of creation (DSN-24). */
export function firstRunProfile(name: string, packs: PackList["packs"], order: number): CreateProfile {
  const installed = installedSubjects(packs);
  const level = installed.length === 0 || installed.some((s) => s.level === "O") ? "O" : "A";
  const subjects = [...new Set(installed.filter((s) => s.level === level).map((s) => s.subject))];
  return {
    display_name: name.trim(),
    avatar: `avatar-${(order % 8) + 1}`,
    level,
    subjects: subjects.length > 0 ? subjects : [...SUBJECT_NAMES],
    age_band: "13_15",
  };
}
