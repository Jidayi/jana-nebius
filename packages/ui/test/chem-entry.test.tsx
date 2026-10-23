import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import goldens from "../gallery/chem-entry-golden.json";
import { EntryEditor, type EntryHandle } from "../src/composer/EntryEditor.js";
import { LocaleProvider } from "../src/i18n.js";
afterEach(cleanup);
test.each(goldens)("inp08_chem_entry_golden: $id", async ({ source, serialised, latex }) => {
  const ref = createRef<EntryHandle>(), sent = vi.fn((_text: string, _pasted: boolean) => false);
  const view = render(<LocaleProvider locale="en"><EntryEditor ref={ref} mode="chem" initialText={`\\(${source}\\)`} label="Expression" placeholder="" onSubmit={sent} /></LocaleProvider>);
  await waitFor(() => expect(view.container.querySelector("annotation")?.textContent).toBe(latex));
  expect(view.container.querySelector("math")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { description: /Maths/ }));
  const input = screen.getByRole("textbox", { name: "Maths as typed" });
  expect((input as HTMLInputElement).value).toBe(source); // the editing source retains the original hydrate notation
  fireEvent.change(input, { target: { value: "cl" } }); fireEvent.keyDown(input, { key: "Escape" });
  await waitFor(() => expect(view.container.querySelector("annotation")?.textContent).toBe(latex));
  act(() => ref.current?.submit()); expect(sent).toHaveBeenCalledWith(serialised, false);
  expect(ref.current?.blocks()).toEqual([{ type: "text", text: serialised }]);
});
test("invalid element case gets a question, preserves source and never autocorrects", async () => {
  const ref = createRef<EntryHandle>(), sent = vi.fn(() => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} mode="chem" initialText="\\(H2O\\)" label="Expression" placeholder="" onSubmit={sent} /></LocaleProvider>);
  fireEvent.click(await screen.findByRole("button", { description: /Maths/ }));
  const input = screen.getByRole("textbox", { name: "Maths as typed" }) as HTMLInputElement;
  fireEvent.change(input, { target: { value: "cl" } }); fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.getByText("Is 'Cl' what you meant? Element symbols are case-sensitive. Check character 1.")).toBeTruthy();
  expect(input.value).toBe("cl"); act(() => ref.current?.submit()); expect(sent).not.toHaveBeenCalled();
});
