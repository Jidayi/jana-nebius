// The way from the conversation to an installed lesson (UXS-20 "Tutor unsure": "Open lesson", PRD-05): the app supplies
// how to open one; without a provider (a component shown on its own) the notice renders without its action.
import { createContext, useContext, type ReactNode } from "react";

const TopicLink = createContext<((topicId: string) => void) | null>(null);

const LessonLink = createContext<((lessonId: string) => void) | null>(null);

export function LessonLinkProvider({ open, openTopic, children }: { open: (lessonId: string) => void; openTopic?: (topicId: string) => void; children: ReactNode }) {
  return <LessonLink.Provider value={open}><TopicLink.Provider value={openTopic ?? null}>{children}</TopicLink.Provider></LessonLink.Provider>;
}

export function useOpenLesson(): ((lessonId: string) => void) | null {
  return useContext(LessonLink);
}

/** The lesson an engine notice's action opens (`open_lesson:<lesson id>`), or null for any other action. */
export function lessonOfCommand(command: string | undefined): string | null {
  const found = /^open_lesson:(les\.[a-z0-9._]+)$/.exec(command ?? "");
  return found?.[1] ?? null;
}


export function useOpenTopic(): ((topicId: string) => void) | null { return useContext(TopicLink); }
export function topicOfCommand(command: string | undefined): string | null {
  return /^open_topic:(cur\.(?:mth|phy|chm|bio|acc)\.(?:o|a)\.[a-z0-9._]+)$/.exec(command ?? "")?.[1] ?? null;
}
