import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { EntryEditor, type EntryHandle } from "../src/composer/EntryEditor.js";
import { LocaleProvider } from "../src/i18n.js";
afterEach(cleanup);
const questions = Array.from({ length: 5 }, (_, index) => `${index + 1}. Find value ${index + 1}?`).join("\n");
for (const mime of ["text/plain", "text/html"] as const) for (const source of ["paste", "drop"] as const) test(`inp13_bulk_paste_picker: ${mime} ${source} starts no turn before selection and explicit Send`, () => {
  const ref = createRef<EntryHandle>(), sent = vi.fn((_text: string, _pasted: boolean) => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} initialText="Previous draft" label="Question" placeholder="" onSubmit={sent} /></LocaleProvider>);
  const box = screen.getByRole("textbox", { name: "Question" }), data = { getData: (type: string) => type === mime ? mime === "text/plain" ? questions : `<ol>${Array.from({ length: 5 }, (_, i) => `<li>Find value ${i + 1}?</li>`).join("")}</ol>` : "", files: [] };
  if (source === "paste") fireEvent.paste(box, { clipboardData: data }); else fireEvent.drop(box, { dataTransfer: data });
  const picker = screen.getByRole("group", { name: /Choose one question/ });
  expect(within(picker).getAllByRole("button")).toHaveLength(6); expect(ref.current?.text()).toBe("Previous draft");
  act(() => ref.current?.submit()); expect(sent).not.toHaveBeenCalled();
  fireEvent.click(within(picker).getByRole("button", { name: "Question 3: Find value 3?" }));
  expect(screen.queryByRole("group", { name: /Choose one question/ })).toBeNull();
  expect(ref.current?.text()).toBe("Find value 3?"); expect(sent).not.toHaveBeenCalled();
  act(() => ref.current?.submit()); expect(sent).toHaveBeenCalledExactlyOnceWith("Find value 3?", true);
});
for (const cancel of ["button", "escape"] as const) test(`inp13_bulk_paste_picker: ${cancel} retains the prior typed draft and its origin`, () => {
  const ref = createRef<EntryHandle>(), sent = vi.fn((_text: string, _pasted: boolean) => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} initialText="Typed before the paste" label="Question" placeholder="" onSubmit={sent} /></LocaleProvider>);
  fireEvent.paste(screen.getByRole("textbox", { name: "Question" }), { clipboardData: { getData: (type: string) => type === "text/plain" ? questions : "" } });
  const picker = screen.getByRole("group", { name: /Choose one question/ });
  if (cancel === "button") fireEvent.click(within(picker).getByRole("button", { name: "Cancel" }));
  else fireEvent.keyDown(within(picker).getByRole("button", { name: "Question 1: Find value 1?" }), { key: "Escape" });
  expect(screen.queryByRole("group", { name: /Choose one question/ })).toBeNull();
  expect(ref.current?.text()).toBe("Typed before the paste"); expect(sent).not.toHaveBeenCalled();
  act(() => ref.current?.submit()); expect(sent).toHaveBeenCalledExactlyOnceWith("Typed before the paste", false);
});


test("numbered working steps remain a multiline draft rather than a question picker", () => {
  const ref = createRef<EntryHandle>(), sent = vi.fn(() => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} multiline label="Working" placeholder="" onSubmit={sent} /></LocaleProvider>);
  fireEvent.paste(screen.getByRole("textbox", { name: "Working" }), { clipboardData: { getData: (type: string) => type === "text/plain" ? questions : "" } });
  expect(screen.queryByRole("group", { name: /Choose one question/ })).toBeNull();
  expect(ref.current?.text()).toBe(questions); expect(sent).not.toHaveBeenCalled();
});
test("cancelling a second bulk paste preserves the origin of text already pasted", () => {
  const ref = createRef<EntryHandle>(), sent = vi.fn((_text: string, _pasted: boolean) => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} label="Question" placeholder="" onSubmit={sent} /></LocaleProvider>);
  const box = screen.getByRole("textbox", { name: "Question" });
  for (const text of ["Earlier pasted draft", questions]) fireEvent.paste(box, { clipboardData: { getData: (type: string) => type === "text/plain" ? text : "" } });
  fireEvent.click(within(screen.getByRole("group", { name: /Choose one question/ })).getByRole("button", { name: "Cancel" }));
  act(() => ref.current?.submit()); expect(sent).toHaveBeenCalledExactlyOnceWith("Earlier pasted draft", true);
});
