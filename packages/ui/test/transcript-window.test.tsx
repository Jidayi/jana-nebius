import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { Composer } from "../src/composer/Composer.js";
import { afterEach, expect, test } from "vitest";
import { Transcript } from "../src/transcript/Transcript.js";
import { protectedRows, signature } from "../src/transcript/window.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(cleanup);
function longSession() {
  const f = new Fixture(); const ids: string[] = [];
  for (let i = 0; i < 500; i++) { const cli = f.send(`Student question ${i}.`); ids.push(f.startTurn(cli)); f.text(`Unique explanation number ${i}.`); f.end(); }
  return { f, ids };
}
test("uia17_long_session_scroll: 500 turns keep bounded DOM and find unmounted stored text", () => {
  const { f, ids } = longSession(); const { container } = f.render(<Transcript sessionId={SESSION} />);
  expect(container.querySelectorAll("[data-row-key]").length).toBeLessThan(40);
  expect(container.querySelectorAll("*").length).toBeLessThan(3000);
  expect(container.querySelector(`[data-turn-id="${ids[0]}"]`)).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "Find in this conversation" }), { target: { value: "Unique explanation number 0." } });
  expect(screen.getByText("Unique explanation number 0.")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("1 of 1 matches");
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Unique explanation number 241." } });
  expect(screen.getByText("Unique explanation number 241.")).toBeTruthy();
  expect(container.querySelectorAll("*").length).toBeLessThan(3000);
});
test("linked history targets mount before focus, and focused turns remain during scrolling", () => {
  const { f, ids } = longSession(); const { container } = f.render(<Transcript sessionId={SESSION} focusTurnId={ids[4]} />);
  const node = container.querySelector<HTMLElement>(`[data-turn-id="${ids[4]}"]`)!;
  expect(node).not.toBeNull();
  act(() => { node.tabIndex = -1; node.focus(); });
  const log = screen.getByRole("log"); fireEvent.scroll(log, { target: { scrollTop: 100000 } });
  expect(container.querySelector(`[data-turn-id="${ids[4]}"]`)).toBe(node);
  expect(document.activeElement).toBe(node);
});
test("live and open-card turns are pinned; height signatures invalidate on content edits", () => {
  const f = new Fixture(); const id = f.startTurn(); const part = f.text("Starting", false);
  const before = signature(f.holder.getState(), `t:${id}`);
  f.emit({ type: "text.delta", part_id: part, delta: " more" });
  expect(signature(f.holder.getState(), `t:${id}`)).not.toBe(before);
  expect(protectedRows(f.holder.getState(), [`t:${id}`]).has(`t:${id}`)).toBe(true);
  f.end(); expect(protectedRows(f.holder.getState(), [`t:${id}`]).size).toBe(0);
  act(() => f.holder.update((s) => ({ ...s, parts: { ...s.parts, [part]: { ...s.parts[part]!, card: { request_id: "r", card: { type: "question" } as never, state: "open" } } } })));
  expect(protectedRows(f.holder.getState(), [`t:${id}`]).has(`t:${id}`)).toBe(true);
});

test("session changes clear search and window state", () => {
  const { f } = longSession();
  function SwitchSession() {
    const [session, setSession] = useState(SESSION);
    return <><button onClick={() => setSession((id) => id === SESSION ? "ses_other" : SESSION)}>Switch conversation</button><Transcript sessionId={session} /></>;
  }
  f.render(<SwitchSession />);
  fireEvent.change(screen.getByRole("textbox", { name: "Find in this conversation" }), { target: { value: "Synthetic private query" } });
  fireEvent.click(screen.getByRole("button", { name: "Switch conversation" }));
  fireEvent.click(screen.getByRole("button", { name: "Switch conversation" }));
  expect((screen.getByRole("textbox", { name: "Find in this conversation" }) as HTMLInputElement).value).toBe("");
});

test("streaming leaves the Ask editor focusable and editable while submission stays blocked", () => {
  const f = new Fixture(); const id = f.startTurn(); const part = f.text("Still explaining", false);
  f.render(<Composer sessionId={SESSION} />);
  const box = screen.getByRole("textbox", { name: "Message to the tutor" });
  expect(box.getAttribute("contenteditable")).toBe("true");
  act(() => (box as HTMLElement).focus());
  f.emit({ type: "text.delta", part_id: part, delta: " more" }, id);
  expect(document.activeElement).toBe(box);
  expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
});
