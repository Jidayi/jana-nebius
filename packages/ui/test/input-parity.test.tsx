import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { extensions, mathNodes, serialise } from "../src/composer/editor.js";
import prose from "../gallery/prose-shortcuts.json";
import golden from "../gallery/shortcut-golden.json";
import { createRef } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { isMathShortcut, type EntryMode } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { EntryEditor, PALETTES, type EntryHandle } from "../src/composer/EntryEditor.js";

const shortcutGolden = golden as [string, string, EntryMode, string, string, string, string][];
const examples: Record<string, string[]> = {
  basic: ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "2+3", "5-2", "2*3", "6/2", "x=2", "(2)", "frac(a,b)", "x^2", "sqrt(9)", "cbrt(8)", "root(3,8)", "x+-2", "pi", "30deg"],
  algebra: ["x_1", "abs(-2)", "x<=2", "x>=2", "x!=2", "sin(2)", "cos(2)", "tan(2)", "asin(1)", "acos(1)", "atan(1)", "log(10)", "ln(2)", "exp(2)", "x~=2", "alpha", "beta", "lambda", "mu", "rho", "omega", "Delta", "theta", "inf", "x->0"],
  units: ["3 m", "3 s", "3 kg", "3 N", "3 J", "3 W", "3 Pa", "3 V", "3 A", "3 mol", "3 dm^3", "3 cm^3", "3 degC", "3 K", "3 ohm", "3 kohm", "3 um", "3 mm", "3 km", "3 MPa", "3 m^-1", "3 s^-2"],
  chem: ["H2O", "SO4^2-", "Na^+", "Cl^-", "Ca^2+", "Na(s)", "H2O(l)", "CO2(g)", "NaCl(aq)", "CuSO4.5H2O", "H2 -> H2", "N2 <=> N2", "CaCO3 ->[heat] CaO", "Delta"],
};
const baseRows = PALETTES.flatMap((p) => p.entries.map((source, index) => [p.key, p.mode === "chem" && source === "Delta" ? "maths" : p.mode, source, examples[p.key]?.[index], examples[p.key]?.[index]] as const));
const rows: readonly (readonly [string, EntryMode, string, string | undefined, string | undefined])[] = [...baseRows,
  ["basic", "maths", "□^□", "x^(n+1)", "x^(n+1)"], ["algebra", "maths", "□_□", "a_(n-1)", "a_(n-1)"],
  ["basic", "maths", "frac(□,□)", "frac(a,b)", "a/b"], ["basic", "maths", "□/□", "(x+1)/(x-1)", "(x+1)/(x-1)"],
  ["basic", "maths", "□*□", "a*b", "a.b"], ["algebra", "maths", "abs(□)", "abs(x)", "|x|"],
];
let shortcutEditor: Editor | null = null;
function Shortcut({ mode, source }: { mode: EntryMode; source: string }) {
  const editor = useEditor({ extensions: extensions("", mode), content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: source }] }] } });
  shortcutEditor = editor; return <EditorContent editor={editor} />;
}
afterEach(() => { cleanup(); vi.useRealTimers(); });
function mount(mode: EntryMode, initialText = "") {
  const ref = createRef<EntryHandle>(), sent = vi.fn((_text: string, _pasted: boolean) => false);
  const view = render(<LocaleProvider locale="en"><EntryEditor ref={ref} mode={mode} initialText={initialText} label="Expression" placeholder="" onSubmit={sent} /></LocaleProvider>);
  return { ...view, ref, sent };
}

test.each(rows)("loc21_maths_input_parity: %s %s %s", async (tab, mode, source, example, typed) => {
  expect(example).toBeDefined(); expect(examples[tab]).toHaveLength(PALETTES.find((p) => p.key === tab)!.entries.length);
  const buttonPath = mount(mode);
  fireEvent.click(screen.getByRole("button", { name: "Maths keyboard" }));
  fireEvent.click(screen.getByRole("tab", { name: tab === "chem" ? "Chemistry" : tab[0]!.toUpperCase() + tab.slice(1) }));
  const toolbar = screen.getByRole("toolbar");
  const key = within(toolbar).getAllByRole("button").find((b) => b.getAttribute("data-key") === source)!;
  expect(key.getAttribute("aria-label")).toBeTruthy(); fireEvent.click(key);
  if (source.includes("□")) {
    const edit = await screen.findByRole("textbox", { name: "Maths as typed" });
    fireEvent.change(edit, { target: { value: example } }); fireEvent.keyDown(edit, { key: "Enter" });
  }
  await waitFor(() => {
    const latex = buttonPath.container.querySelector("[data-math-node]")?.getAttribute("data-latex");
    expect(latex).toBeTruthy(); expect(latex).not.toContain("□");
    expect(buttonPath.container.querySelector("annotation")?.textContent).toBe(latex);
  });
  act(() => buttonPath.ref.current?.submit()); expect(buttonPath.sent).toHaveBeenCalledTimes(1);
  const serialised = buttonPath.sent.mock.calls[0]![0];
  const annotation = buttonPath.container.querySelector("annotation")?.textContent;
  expect(annotation).toBeTruthy();
  cleanup();
  const typedPath = mount(mode, `\\(${typed}\\)`);
  await waitFor(() => expect(typedPath.container.querySelector("annotation")).not.toBeNull());
  act(() => typedPath.ref.current?.submit()); expect(typedPath.sent).toHaveBeenCalledTimes(1);
  expect(typedPath.sent.mock.calls[0]![0]).toBe(serialised);
  expect(typedPath.container.querySelector("annotation")?.textContent).toBe(annotation);
  if (mode === "maths" && isMathShortcut(typed ?? "")) {
    cleanup(); shortcutEditor = null;
    render(<LocaleProvider locale="en"><Shortcut mode={mode} source={typed ?? ""} /></LocaleProvider>);
    const editor: Editor | null = shortcutEditor;
    if (!editor) throw new Error("Shortcut editor not created");
    act(() => {
      const pos = editor.state.doc.content.size - 1; editor.commands.setTextSelection(pos);
      editor.view.someProp("handleTextInput", (handler) => handler(editor.view, pos, pos, " ", () => editor.state.tr.insertText(" ")));
    });
    expect(mathNodes(editor.getJSON())).toHaveLength(1);
    expect(serialise(editor.getJSON()).trim()).toBe(serialised);
  }
});

test("input MathML is announced only after a typing pause", async () => {
  vi.useFakeTimers(); mount("maths");
  fireEvent.click(screen.getByRole("button", { name: "Maths keyboard" }));
  fireEvent.click(screen.getByRole("tab", { name: "Basic" }));
  fireEvent.click(screen.getByRole("button", { name: "Fraction: frac(□,□)" }));
  await act(async () => { vi.advanceTimersByTime(20); });
  const edit = screen.getByRole("textbox", { name: "Maths as typed" });
  fireEvent.change(edit, { target: { value: "frac(1,2)" } }); act(() => vi.advanceTimersByTime(499));
  expect(document.querySelector("[data-input-announcement]")?.textContent).toBe("");
  fireEvent.change(edit, { target: { value: "frac(1,3)" } }); act(() => vi.advanceTimersByTime(499));
  expect(document.querySelector("[data-input-announcement]")?.textContent).toBe("");
  act(() => vi.advanceTimersByTime(1));
  expect(document.querySelector("[data-input-announcement] annotation")?.textContent).toBe("\\frac{1}{3}");
});

test.each(shortcutGolden)("inp04_shortcut_button_parity: %s %s %s %s %s %s", async (_area, tab, mode, source, buttonInput, typedInput, latex) => {
  expect(PALETTES.find((p) => p.key === tab)?.entries).toContain(source);
  const chosen = mount(mode);
  fireEvent.click(screen.getByRole("button", { name: "Maths keyboard" }));
  fireEvent.click(screen.getByRole("tab", { name: tab === "chem" ? "Chemistry" : tab[0]!.toUpperCase() + tab.slice(1) }));
  fireEvent.click(within(screen.getByRole("toolbar")).getAllByRole("button").find((b) => b.getAttribute("data-key") === source)!);
  if (source.includes("□")) {
    const edit = await screen.findByRole("textbox", { name: "Maths as typed" });
    fireEvent.change(edit, { target: { value: buttonInput } }); fireEvent.keyDown(edit, { key: "Enter" });
  }
  await waitFor(() => expect(chosen.container.querySelector("[data-math-node]")?.getAttribute("data-latex")).toBe(latex));
  await waitFor(() => expect(chosen.container.querySelector("annotation")?.textContent).toBe(latex));
  act(() => chosen.ref.current?.submit()); expect(chosen.sent).toHaveBeenCalledTimes(1);
  cleanup();
  const typed = mount(mode, `\\(${typedInput}\\)`);
  await waitFor(() => expect(typed.container.querySelector("annotation")?.textContent).toBe(latex));
  act(() => typed.ref.current?.submit()); expect(typed.sent).toHaveBeenCalledTimes(1);
});

test("shortcut goldens cover each S2 row and every Greek letter", () => {
  expect(new Set(shortcutGolden.map((row) => row[0]))).toEqual(new Set(["power", "subscript", "roots", "fractions", "multiplication", "relations", "greek", "degrees", "arrows", "absolute", "infinity"]));
  expect(shortcutGolden.filter((row) => row[0] === "greek").map((row) => row[5])).toEqual(["pi", "theta", "alpha", "beta", "lambda", "mu", "rho", "omega", "Delta"]);
});

test("inp04_no_false_conversion: 500 classroom prose sentences through the typing rule", () => {
  expect(prose).toHaveLength(500); expect(new Set(prose).size).toBe(500);
  shortcutEditor = null;
  render(<LocaleProvider locale="en"><Shortcut mode="maths" source="" /></LocaleProvider>);
  const editor = shortcutEditor;
  if (!editor) throw new Error("Shortcut editor not created");
  for (const sentence of prose) {
    act(() => {
      editor.commands.clearContent();
      for (const token of sentence.split(" ")) {
        editor.commands.insertContent(token);
        const pos = editor.state.selection.to;
        const handled = editor.view.someProp("handleTextInput", (handler) => handler(editor.view, pos, pos, " ", () => editor.state.tr.insertText(" ")));
        if (!handled) editor.commands.insertContent(" ");
      }
    });
    expect(mathNodes(editor.getJSON()), sentence).toEqual([]);
    expect(serialise(editor.getJSON()).trim(), sentence).toBe(sentence);
  }
});
