import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Editor } from "@tiptap/core";
import { createRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import prose from "../gallery/prose-shortcuts.json";
import { segments } from "../src/composer/maths.js";
import fixtures from "../gallery/paste-golden.json";
import { EntryEditor, type EntryHandle } from "../src/composer/EntryEditor.js";
import { clipboardText } from "../src/composer/paste.js";
import { LocaleProvider } from "../src/i18n.js";
afterEach(cleanup);
for (const source of ["paste", "drop"] as const) test.each(fixtures)(`inp13_paste_normalisation: ${source} $id`, async (fixture) => {
  const data = { getData: (type: string) => (fixture.clipboard as Record<string, string>)[type] ?? "" };
  expect(clipboardText(data)).toBe(fixture.text);
  const ref = createRef<EntryHandle>(), sent = vi.fn((_text: string, _pasted: boolean) => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} label="Expression" placeholder="" onSubmit={sent} /></LocaleProvider>);
  const box = screen.getByRole("textbox", { name: "Expression" }) as HTMLElement & { editor: Editor };
  if (source === "paste") fireEvent.paste(box, { clipboardData: data });
  else fireEvent.drop(box, { dataTransfer: { ...data, files: [] } });
  expect(box.editor.getJSON()).toEqual(fixture.document);
  const math = fixture.document.content[0]!.content.filter((node) => node.type === "math");
  await waitFor(() => expect(box.querySelectorAll("[data-math-node]")).toHaveLength(math.length));
  expect(box.querySelector("a, script, img:not(.ProseMirror-separator), iframe, object, style, [onclick], [onerror], [src]")).toBeNull();
  act(() => ref.current?.submit()); expect(sent).toHaveBeenCalledWith(fixture.serialised, true);
  expect(ref.current?.blocks()).toEqual([{ type: "text", text: fixture.serialised }]);
});


test("clipboard maths never consumes classroom prose, sentence punctuation or rejected runs", () => {
  for (const sentence of [...prose, "time−table", "√ unknown", "× 2"]) {
    expect(segments(sentence).every((part) => part.kind === "text"), sentence).toBe(true);
    expect(segments(sentence).map((part) => part.kind === "text" ? part.text : "").join("")).toBe(sentence);
  }
  expect(segments("3. x²")).toEqual([{ kind: "text", text: "3. " }, { kind: "math", source: "x²", latex: "x^{2}" }]);
  expect(segments("See “x²”.")).toEqual([{ kind: "text", text: "See “" }, { kind: "math", source: "x²", latex: "x^{2}" }, { kind: "text", text: "”." }]);
});
