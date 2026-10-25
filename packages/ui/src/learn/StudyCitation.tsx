import { useRef } from "react";
import type { StudyContracts as W } from "@jana/client-core";
import { useT } from "../i18n.js";
import { Button, MenuButton, Tooltip } from "../primitives/index.js";
import { pdfFormulaPreview, StudySourceText } from "./StudyText.js";

/** Match the source and revision too: chunk ids alone must never identify another material's location. */
export const citationKey = (ref: Pick<W.Citation, "source_id" | "revision" | "chunk_id">) => `${ref.source_id}:${ref.revision}:${ref.chunk_id}`;

const timestamp = (ms: number) => {
  const seconds = Math.floor(ms / 1000), minutes = Math.floor(seconds / 60);
  const tail = `${String(minutes % 60).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  return minutes >= 60 ? `${Math.floor(minutes / 60)}:${tail}` : tail;
};

/** Quiet location badges keep the prose readable without losing the exact verified passage. */
export function StudyCitation({ citation, locator, sourceTitle, number, disabled, onOpen, passages = [citation] }: {
  citation: W.Citation; locator?: W.Locator | undefined; sourceTitle?: string | undefined; number: number;
  disabled?: boolean | undefined; onOpen: (citation: W.Citation) => void; passages?: readonly W.Citation[];
}) {
  const t = useT();
  const trigger = useRef<HTMLButtonElement | null>(null);
  const label = locator?.kind === "page" ? t("study.ref.page", { page: locator.page })
    : locator?.kind === "slide" ? t("study.ref.slide", { slide: locator.slide })
    : locator?.kind === "time" ? timestamp(locator.start_ms)
    : locator?.kind === "note" || locator?.kind === "text" ? t("study.ref.paragraph", { paragraph: locator.paragraph })
    : `[${number}]`;
  const location = locator?.kind === "page" ? t("study.source_page", { page: locator.page })
    : locator?.kind === "time" ? t("study.ref.time", { time: label })
    : locator?.kind === "slide" ? t("study.ref.slide_full", { slide: locator.slide })
    : locator?.kind === "note" || locator?.kind === "text" ? t("study.ref.paragraph_full", { paragraph: locator.paragraph })
    : t("study.ref.number", { number });
  const detail = [sourceTitle, location, citation.revision > 1 ? t("study.revision", { revision: citation.revision }) : null].filter(Boolean).join(" · ");
  if (passages.length > 1) {
    const description = `${detail} · ${t("study.ref.passages", { count: passages.length })}`;
    return <MenuButton label={description} align="start" descriptive
      trigger={(menuProps) => <Tooltip text={description}>{(tipProps) => <Button {...menuProps} {...tipProps}
        ref={(button: HTMLButtonElement | null) => { trigger.current = button; menuProps.ref(button); }}
        size="xs" tone="reference" aria-label={description} disabled={disabled}>{label}</Button>}</Tooltip>}
      items={passages.map((ref, i) => {
        const formulaProse = locator?.kind === "page" ? pdfFormulaPreview(ref.quote) : null;
        const preview = formulaProse ?? ref.quote;
        return { id: String(i), label: t("study.ref.passage", { number: i + 1 }),
          hint: <span className="flex flex-col gap-1">{preview && <StudySourceText text={preview.length > 160 ? `${preview.slice(0, 160)}…` : preview} />}{formulaProse !== null && <span>{t("study.original_pdf_formula")}</span>}</span>,
          onSelect: () => { trigger.current?.focus(); onOpen(ref); }, disabled: !!disabled };
      })} />;
  }
  return <Tooltip text={detail}>{(props) => <Button {...props} size="xs" tone="reference" aria-label={detail} disabled={disabled} onClick={() => onOpen(citation)}>{label}</Button>}</Tooltip>;
}

/** Group within one point, and only within the same material and revision. Every passage remains selectable. */
export function StudyCitations({ citations, locate, title, disabled, onOpen }: {
  citations: readonly W.Citation[]; locate: (ref: W.Citation) => W.Locator | undefined;
  title: (ref: W.Citation) => string | undefined; disabled?: boolean; onOpen: (ref: W.Citation) => void;
}) {
  const groups = new Map<string, { refs: [W.Citation, ...W.Citation[]]; locator: W.Locator | undefined; number: number }>();
  citations.forEach((ref, i) => {
    const locator = locate(ref);
    const key = locator?.kind === "page" ? `${ref.source_id}:${ref.revision}:page:${locator.page}` : `reference:${i}`;
    const group = groups.get(key);
    if (group) group.refs.push(ref);
    else groups.set(key, { refs: [ref], locator, number: i + 1 });
  });
  return <div className="flex flex-wrap gap-2">{Array.from(groups, ([key, group]) => <StudyCitation key={key}
    citation={group.refs[0]} passages={group.refs} locator={group.locator} sourceTitle={title(group.refs[0])}
    number={group.number} disabled={disabled} onOpen={onOpen} />)}</div>;
}
