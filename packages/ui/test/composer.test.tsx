// INP-03: the composer editor model: \(…\) is maths, a single $ never is, and a maths node edits in place.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { afterEach, describe, expect, test } from "vitest";
import { LocaleProvider } from "../src/i18n.js";
import { extensions, insertText, mathNodes, serialise } from "../src/composer/editor.js";
import { normaliseLatex } from "../src/composer/maths.js";

afterEach(() => cleanup());

let current: Editor | null = null;

function Harness() {
  const editor = useEditor({ extensions: extensions("Type here") });
  current = editor;
  return <EditorContent editor={editor} />;
}

function mount(): Editor {
  render(<LocaleProvider locale="en"><Harness /></LocaleProvider>);
  if (current === null) throw new Error("editor not created");
  return current;
}

describe("INP-03", () => {
  test("inp03_no_single_dollar_math", () => {
    const editor = mount();
    act(() => insertText(editor, "Sales of $450 and $300"));
    expect(mathNodes(editor.getJSON())).toEqual([]);
    expect(serialise(editor.getJSON())).toBe("Sales of $450 and $300");
    act(() => insertText(editor, " then \\(x^2\\)"));
    expect(mathNodes(editor.getJSON())).toEqual([{ source: "x^2", latex: "x^{2}" }]);
    expect(serialise(editor.getJSON())).toBe("Sales of $450 and $300 then \\(x^{2}\\)");
    expect(normaliseLatex("v_0 + \\alpha^{2} + a^b")).toBe("v_{0} + \\alpha^{2} + a^{b}");
  });

  test("inp03_click_to_edit", async () => {
    const editor = mount();
    act(() => insertText(editor, "so \\(s^2\\) is"));
    const open = () => screen.findByRole("button", { description: /Maths s\^\{2\}/ });
    // Click opens the source; Esc restores it unchanged.
    fireEvent.click(await open());
    const field = await screen.findByLabelText("Maths as typed");
    expect((field as HTMLInputElement).value).toBe("s^2");
    fireEvent.change(field, { target: { value: "s^3" } });
    fireEvent.keyDown(field, { key: "Escape" });
    expect(mathNodes(editor.getJSON())).toEqual([{ source: "s^2", latex: "s^{2}" }]);
    // Enter commits a re-rendered node.
    fireEvent.click(await open());
    const again = await screen.findByLabelText("Maths as typed");
    fireEvent.change(again, { target: { value: "s_1" } });
    fireEvent.keyDown(again, { key: "Enter" });
    expect(mathNodes(editor.getJSON())).toEqual([{ source: "s_1", latex: "s_{1}" }]);
    expect(await screen.findByRole("button", { description: /Maths s_\{1\}/ })).toBeDefined();
  });
});

test("typed shortcuts convert at a boundary and Backspace restores the source", () => {
  const editor = mount();
  act(() => {
    editor.commands.setContent("<p>x^2</p>");
    const pos = editor.state.doc.content.size - 1;
    editor.commands.setTextSelection(pos);
    editor.view.someProp("handleTextInput", (handler) => handler(editor.view, pos, pos, " ", () => editor.state.tr.insertText(" ")));
  });
  expect(mathNodes(editor.getJSON())).toEqual([{ source: "x^2", latex: "x^{2}" }]);
  act(() => { expect(editor.commands.undoInputRule()).toBe(true); });
  expect(mathNodes(editor.getJSON())).toEqual([]);
  expect(serialise(editor.getJSON())).toBe("x^2 ");
});
