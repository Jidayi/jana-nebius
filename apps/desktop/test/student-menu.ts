// The student menu at the sidebar's foot (D115): Settings and Switch student live in it. Tests open it
// the way a student does, from the student row, and pick the item by its words.
import { fireEvent, screen, waitFor } from "@testing-library/react";

function trigger(): HTMLElement {
  const row = document.querySelector<HTMLElement>("[data-student-menu]");
  if (row === null) throw new Error("no student menu on screen");
  return row;
}

/** Opens the student menu and returns its item named `name` (Settings carries its shortcut after its name). */
export function menuItem(name: "Settings" | "Switch student" | string): HTMLElement {
  if (trigger().getAttribute("aria-expanded") !== "true") fireEvent.click(trigger());
  return screen.getByRole("menuitem", { name: name === "Settings" ? /^Settings/ : name });
}

/** As `menuItem`, once the student menu is on screen. */
export async function findMenuItem(name: string): Promise<HTMLElement> {
  await waitFor(() => trigger());
  return menuItem(name);
}
