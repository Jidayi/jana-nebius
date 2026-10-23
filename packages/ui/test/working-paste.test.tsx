import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { SessionController } from "@jana/client-core";
import lines from "../gallery/working-paste-golden.json";
import { WorkingEntry } from "../src/board/WorkingEntry.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
import { Fixture, SESSION, id } from "./harness.js";
afterEach(cleanup);
function mount() {
  const f = new Fixture(); f.startTurn(); f.end(); const posts: Record<string, unknown>[] = [];
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, f.holder, SESSION, {
    fetch: async (_url, init) => {
      if (init?.method !== "POST") return Response.json({ document: {}, revision: 0 });
      posts.push(JSON.parse(String(init.body))); return Response.json({ turn_id: id("trn"), message_id: id("msg") }, { status: 202 });
    },
  });
  render(<LocaleProvider locale="en"><StoreProvider holder={f.holder} session={session}><WorkingEntry sessionId={SESSION} /></StoreProvider></LocaleProvider>);
  return { session, posts, box: screen.getByRole("textbox", { name: "Your working" }) };
}
function paste(box: HTMLElement, text: string) { fireEvent.paste(box, { clipboardData: { getData: (type: string) => type === "text/plain" ? text : "" } }); }
test("inp12_paste_splits_lines: eight numbered working lines reach the real controller in order", async () => {
  const { session, posts, box } = mount();
  try {
    paste(box, lines.join("\r\n"));
    expect([...document.querySelectorAll("[data-line-numbers] > div")].map((el) => el.textContent)).toEqual(lines.map((_, index) => String(index + 1)));
    expect(box.querySelectorAll("br")).toHaveLength(7);
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ intent: "board_line", content: [{ type: "text", text: lines.join("\n") }] });
    expect(box.textContent).not.toBe(""); // waiting for the authoritative check does not discard the draft
  } finally { session.close(); }
});
test.each([[Array.from({ length: 31 }, () => "x=2").join("\n"), "Use up to 30 working lines."],
  ["x".repeat(2001), "That's too long for one line. Split it into steps. Check character 2001."]])("invalid working is retained without any request", async (source, hint) => {
  const { session, posts, box } = mount();
  try {
    paste(box, source); fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText(hint)).toBeTruthy(); expect(posts).toHaveLength(0); expect(box.textContent).not.toBe("");
  } finally { session.close(); }
});
