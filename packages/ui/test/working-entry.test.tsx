import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { SessionController } from "@jana/client-core";
import { Board } from "../src/board/Board.js";
import { WorkingEntry } from "../src/board/WorkingEntry.js";
import { StoreProvider } from "../src/store.js";
import { Fixture, SESSION, id } from "./harness.js";

afterEach(cleanup);

test("failed checks keep working; successful checks clear it", () => {
  const f = new Fixture();
  f.startTurn(); f.end();
  let latest = "";
  const session = { sendWorking: vi.fn((text: string) => { latest = f.send(text); return latest; }) } as unknown as SessionController;
  f.render(<StoreProvider holder={f.holder} session={session}><WorkingEntry sessionId={SESSION} /></StoreProvider>);
  const box = screen.getByRole("textbox", { name: "Your working" });
  fireEvent.paste(box, { clipboardData: { getData: (type: string) => type === "text/plain" ? "s=10" : "" } });
  fireEvent.click(screen.getByRole("button", { name: "Check my working" }));
  f.startTurn(latest); f.end("error");
  expect(box.textContent).toBe("s=10");
  fireEvent.click(screen.getByRole("button", { name: "Check my working" }));
  f.startTurn(latest); f.end();
  expect(box.textContent).toBe("");
  expect(session.sendWorking).toHaveBeenCalledTimes(2);
});

// INP-11: a tutor line exposes no edit action by pointer or keyboard; a student's line edits under its own step id.
// The core's half (an edit naming a tutor line changes nothing) is the test of the same name in agent-core.
test("inp11_tutor_lines_read_only", () => {
  const f = new Fixture();
  f.startTurn(); f.end();
  const board = id("brd");
  const own = id("stp");
  const teacher = id("stp");
  for (const [index, stepId, owner] of [[0, teacher, "tutor"], [1, own, "student"]] as const) {
    f.emit({ type: "board.step", board_id: board, step_id: stepId, index, latex: "s=10", reason: null,
      owner, status: "unchecked", check_id: null, error: null }, null);
  }
  const session = { sendBoardLine: vi.fn((_step: string, text: string) => f.send(text)) } as unknown as SessionController;
  f.render(<StoreProvider holder={f.holder} session={session}><Board sessionId={SESSION} /></StoreProvider>);
  expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
  const row = document.querySelector<HTMLElement>(`[data-step-id="${teacher}"]`)!;
  expect(within(row).queryByRole("button", { name: "Edit" })).toBeNull();
  fireEvent.keyDown(row, { key: "e" });
  fireEvent.keyDown(row, { key: "E" });
  fireEvent.keyDown(row, { key: "Enter" });
  expect(screen.queryByRole("textbox", { name: "Edit your working line" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  const field = screen.getByRole("textbox", { name: "Edit your working line" });
  const entry = field.closest(".border-t") as HTMLElement;
  fireEvent.click(within(entry).getByRole("button", { name: "Check my working" }));
  expect(session.sendBoardLine).toHaveBeenCalledWith(own, "s=10");
});

test.each(["PARSE_REJECTED", "LIMIT_EXCEEDED"])("inp07_parse_error_hints: authoritative %s keeps the working draft", async (kind) => {
  const { SessionController } = await import("@jana/client-core");
  const { waitFor } = await import("@testing-library/react");
  const f = new Fixture(); f.startTurn(); f.end();
  const posts: Record<string, unknown>[] = [];
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, f.holder, SESSION, {
    fetch: async (_url, init) => {
      if (init?.method !== "POST") return new Response(JSON.stringify({ document: {}, revision: 0 }), { status: 200 });
      posts.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ error: { code: "validation_failed", retryable: false, details: {
        input_error: kind, line: 1, position: 2, hint_key: kind === "PARSE_REJECTED" ? "unbalanced_bracket" : "too_long", word: "",
      } } }), { status: 422 });
    },
  });
  try {
    f.render(<StoreProvider holder={f.holder} session={session}><WorkingEntry sessionId={SESSION} /></StoreProvider>);
    const box = screen.getByRole("textbox", { name: "Your working" });
    fireEvent.paste(box, { clipboardData: { getData: (type: string) => type === "text/plain" ? "x^2" : "" } });
    fireEvent.click(screen.getByRole("button", { name: "Check my working" }));
    const hint = kind === "PARSE_REJECTED" ? "There's a bracket without its partner. Check character 3." : "That's too long for one line. Split it into steps. Check character 3.";
    await waitFor(() => expect(screen.getByText(hint)).toBeTruthy());
    expect(box.textContent).toBe("x^2"); expect(posts).toHaveLength(1);
    expect(Object.values(f.holder.getState().boards)).toHaveLength(0);
    expect(Object.values(f.holder.getState().messages).find((m) => m.state === "failed")?.error_details?.input_error).toBe(kind);
  } finally { session.close(); }
});
