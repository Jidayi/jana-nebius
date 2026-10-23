import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { EntryMode } from "@jana/client-core";
import { EntryEditor, type EntryHandle } from "../src/composer/EntryEditor.js";
import { LocaleProvider } from "../src/i18n.js";
afterEach(() => { cleanup(); vi.useRealTimers(); });
const fixtures: [string, EntryMode, number, string][] = [
  ["x=(2", "maths", 4, "There's a bracket without its partner. Check character 5."],
  ["x=□", "maths", 2, "Something is missing here. Check character 3."],
  ["sinx", "maths", 0, "I don’t recognise 'sinx'. Did you mean sin x? Check character 1."],
  ["x=2=3", "maths", 3, "Write one equation per line. Check character 4."],
  ["x".repeat(2001), "maths", 2000, "That's too long for one line. Split it into steps. Check character 2001."],
  ["25 C", "units", 3, "Is C coulombs? For Celsius, write °C. Check character 4."],
];
test.each(fixtures)("inp07_parse_error_hints: %s %s position %i", async (source, mode, position, hint) => {
  vi.useFakeTimers(); const ref = createRef<EntryHandle>(), sent = vi.fn(() => false);
  render(<LocaleProvider locale="en"><EntryEditor ref={ref} mode={mode} initialText={mode === "units" ? "\\(3 m\\)" : "\\(x^2\\)"} label="Expression" placeholder="" onSubmit={sent} /></LocaleProvider>);
  await act(async () => { vi.advanceTimersByTime(20); });
  fireEvent.click(screen.getByRole("button", { description: /Maths/ }));
  const input = screen.getByRole("textbox", { name: "Maths as typed" }) as HTMLInputElement;
  fireEvent.change(input, { target: { value: source } });
  act(() => vi.advanceTimersByTime(599));
  expect(input.getAttribute("aria-invalid")).toBe("false"); expect(document.querySelector("[data-input-error-position]")).toBeNull();
  act(() => vi.advanceTimersByTime(1));
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(document.querySelector("[data-input-error-position]")?.getAttribute("data-input-error-position")).toBe(String(position));
  expect(document.getElementById(input.getAttribute("aria-describedby")!)?.textContent).toBe(hint);
  fireEvent.blur(input); // clicking Send must not silently cancel an invalid edit and submit its old value
  expect(screen.getByRole("textbox", { name: "Maths as typed" })).toBe(input);
  act(() => ref.current?.submit()); expect(sent).not.toHaveBeenCalled(); expect(input.value).toBe(source);
  fireEvent.keyDown(input, { key: "Enter" }); expect(input.value).toBe(source); expect(sent).not.toHaveBeenCalled();
  // Keep accepting keys, reset the pause, then commit a correction and submit it exactly once.
  fireEvent.change(input, { target: { value: mode === "units" ? "4 m" : "x^3" } });
  expect(input.getAttribute("aria-invalid")).toBe("false");
  fireEvent.keyDown(input, { key: "Enter" });
  await act(async () => { vi.advanceTimersByTime(20); });
  act(() => ref.current?.submit()); expect(sent).toHaveBeenCalledTimes(1);
  expect(sent.mock.calls[0]).toEqual([mode === "units" ? "4 m" : "\\(x^{3}\\)", false]);
});
