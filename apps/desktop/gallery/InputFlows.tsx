// Synthetic editor harness with a read-only submission trace; it supplies no model/subject approval evidence.
import { useRef } from "react";
import { EntryEditor, type EntryHandle } from "../../../packages/ui/src/composer/EntryEditor.js";
import { LocaleProvider } from "@jana/ui";
export function InputFlows() {
  const editor = useRef<EntryHandle>(null), sent = useRef<unknown[]>([]);
  Object.defineProperty(globalThis, "__jana_input_evidence", { configurable: true, get: () => ({ sent: sent.current, blocks: editor.current?.blocks(), text: editor.current?.text() }) });
  return <LocaleProvider locale="en"><main data-theme={new URLSearchParams(globalThis.location.search).get("theme") ?? "light"} className="bg-canvas p-6 text-ink"><EntryEditor ref={editor} accounting label="Working" placeholder="" multiline={new URLSearchParams(globalThis.location.search).get("flow") !== "question"} onSubmit={(text, pasted) => {
    sent.current.push({ text, pasted, blocks: editor.current?.blocks() }); return false;
  }} /></main></LocaleProvider>;
}
