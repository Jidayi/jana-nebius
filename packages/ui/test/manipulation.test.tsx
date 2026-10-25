// VSL-42 (D103): every manipulation can be made and checked by keyboard alone, with the value announced; the values
// sent take the form the typed line takes, so the verification tools mark them as they would the typed line.
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { ManipulationPanel, type ManipulableKind } from "../src/board/Manipulation.js";
import { Fixture } from "./harness.js";

afterEach(() => cleanup());

const CASES: [ManipulableKind, string, string[], (string | number)[], string][] = [
  // kind, part, keys pressed per field, a typed value for the last field, the value sent
  ["number_line", "sol.from", ["ArrowUp", "ArrowUp", "PageUp"], [], "6"],
  ["function_graph", "f.root1", ["ArrowRight", "ArrowRight", "ArrowRight", "ArrowRight"], ["0"], "(2, 0)"],
  ["free_body", "W", ["PageUp", "PageUp", "PageUp", "PageUp", "ArrowDown"], ["270"], "39 N at 270"],
];

describe("VSL-42", () => {
  test("vsl42_keyboard_equivalent", () => {
    for (const [kind, part, keys, typed, sent] of CASES) {
      const f = new Fixture();
      let checked: { part_id: string; value: string }[] | null = null;
      f.render(<ManipulationPanel kind={kind} partIds={[part]} prompt="Set it on the diagram" onCheck={(v) => { checked = v; }} />);
      const fields = screen.getAllByRole("spinbutton") as HTMLInputElement[];
      // Every value is reachable by keyboard; arrow keys move the first by the kind's step and the value is announced.
      expect(fields.every((el) => el.tabIndex >= 0)).toBe(true);
      fields[0]!.focus();
      for (const key of keys) fireEvent.keyDown(fields[0]!, { key });
      expect(screen.getByRole("status").textContent).toContain(fields[0]!.value);
      expect(fields[0]!.getAttribute("aria-valuetext")).toContain(fields[0]!.value);
      // The other value is typed, as it can be for any field.
      typed.forEach((value, i) => fireEvent.change(fields[i + 1]!, { target: { value: String(value) } }));
      fireEvent.click(screen.getByRole("button", { name: "Check" }));
      expect(checked).toEqual([{ part_id: part, value: sent }]);
      cleanup();
    }
  });
});
