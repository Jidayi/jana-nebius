import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { EntryMode } from "@jana/client-core";
import { EntryEditor } from "../src/composer/EntryEditor.js";
import { LocaleProvider } from "../src/i18n.js";
afterEach(cleanup);
function show(mode: EntryMode, accounting = false) {
  render(<LocaleProvider locale="en"><EntryEditor mode={mode} accounting={accounting} label="Expression" placeholder="" onSubmit={() => false} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Maths keyboard" }));
}
test("inp06_palette_keyboard: subject defaults and separate remembered tabs", () => {
  for (const [mode, accounting, name] of [["maths", false, "Basic"], ["units", false, "Units"], ["chem", false, "Chemistry"], ["maths", true, "Accounting"]] as const) {
    show(mode, accounting); expect(screen.getByRole("tab", { selected: true }).textContent).toBe(name); cleanup();
  }
  show("maths"); fireEvent.click(screen.getByRole("tab", { name: "Algebra" })); cleanup();
  show("units"); expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Units"); cleanup();
  show("maths"); expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Algebra");
});
test("disabled editor refuses the palette shortcut", () => {
  render(<LocaleProvider locale="en"><EntryEditor disabled label="Expression" placeholder="" onSubmit={vi.fn()} /></LocaleProvider>);
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Expression" }), { key: "m", altKey: true });
  expect(screen.queryByRole("tablist")).toBeNull();
});
