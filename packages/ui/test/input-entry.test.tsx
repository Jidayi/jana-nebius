import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { LocaleProvider } from "../src/i18n.js";
import { EntryEditor, type EntryHandle } from "../src/composer/EntryEditor.js";
import { clipboardText } from "../src/composer/paste.js";

afterEach(cleanup);

function data(values: Record<string, string>) { return { getData: (type: string) => values[type] ?? "" }; }

test("word-processor MathML and web HTML never insert scripts, images or links", () => {
  const text = clipboardText(data({ "text/html": '<p>Work <a href="https://invalid.example">here</a></p><script>alert(1)</script><img src="invalid"><math><mfrac><mn>1</mn><mn>2</mn></mfrac></math>' }));
  expect(text).toBe("Work here\n\\(frac(1,2)\\)");
  const sent = vi.fn(() => true);
  render(<LocaleProvider locale="en"><EntryEditor label="Question" placeholder="Type here" onSubmit={sent} /></LocaleProvider>);
  fireEvent.paste(screen.getByRole("textbox"), { clipboardData: data({ "text/html": '<p>\\(x²\\) &lt;tag&gt;</p><img src="invalid">' }) });
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  expect(sent).toHaveBeenCalledWith("\\(x^{2}\\) <tag>", true);
  expect(document.querySelector('.tiptap a, .tiptap img, .tiptap script')).toBeNull();
});

test("bulk paste starts no turn until one question is chosen and Send is pressed", () => {
  const sent = vi.fn(() => true);
  const ref = createRef<EntryHandle>();
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} label="Question" placeholder="Type here" onSubmit={sent} /></LocaleProvider>);
  const text = Array.from({ length: 5 }, (_, i) => `${i + 1}. Find value ${i + 1}?`).join("\n");
  fireEvent.paste(screen.getByRole("textbox"), { clipboardData: data({ "text/plain": text }) });
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  expect(sent).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Question 3: Find value 3?" }));
  act(() => ref.current?.submit());
  expect(sent).toHaveBeenCalledWith("Find value 3?", true);
});

test("PDF Unicode tokens become editable maths and currency stays text", () => {
  const sent = vi.fn(() => true);
  render(<LocaleProvider locale="en"><EntryEditor label="Question" placeholder="Type here" onSubmit={sent} /></LocaleProvider>);
  fireEvent.paste(screen.getByRole("textbox"), { clipboardData: data({ "text/plain": "Find x²+2x+1 and keep $450." }) });
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  expect(sent).toHaveBeenCalledWith("Find \\(x^{2} + 2 x + 1\\) and keep $450.", true);
});

test("palette slots use Tab, commit a fraction, and invalid drafts remain editable", async () => {
  const ref = createRef<EntryHandle>();
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} label="Question" placeholder="Type here" onSubmit={() => true} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Maths keyboard" }));
  fireEvent.click(screen.getByRole("button", { name: "Fraction: frac(□,□)" }));
  const input = await screen.findByLabelText("Maths as typed") as HTMLInputElement;
  expect(input.selectionStart).toBe(5);
  fireEvent.change(input, { target: { value: "frac(a,□)" } });
  input.setSelectionRange(6, 6);
  fireEvent.keyDown(input, { key: "Tab" });
  expect(input.selectionStart).toBe(7);
  fireEvent.change(input, { target: { value: "frac(a,b)" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(ref.current?.text()).toBe("\\(\\frac{a}{b}\\)");
  fireEvent.click(await screen.findByRole("button", { description: /Maths \\frac/ }));
  const again = screen.getByLabelText("Maths as typed");
  fireEvent.change(again, { target: { value: "frac(a," } });
  fireEvent.keyDown(again, { key: "Enter" });
  expect(screen.getByLabelText("Maths as typed").getAttribute("aria-invalid")).toBe("true");
  expect(ref.current?.text()).toBe("\\(\\frac{a}{b}\\)");
});
