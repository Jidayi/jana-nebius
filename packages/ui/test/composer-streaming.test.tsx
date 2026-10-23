import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { SessionController } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
import { Composer } from "../src/composer/Composer.js";
import { Fixture, SESSION } from "./harness.js";

vi.mock("../src/composer/EntryEditor.js", async () => {
  const { forwardRef, useImperativeHandle, useState } = await import("react");
  return { EntryEditor: forwardRef(function TestEntry(props: { label: string; disabled?: boolean; onChange?: (text: string) => void; onSubmit: (text: string, pasted: boolean) => void }, ref) {
    const [text, setText] = useState("");
    useImperativeHandle(ref, () => ({ focus: vi.fn(), text: () => text, clear: () => setText(""), blocks: () => [{ type: "text", text }], submit: () => props.onSubmit(text, false) }));
    return <textarea aria-label={props.label} disabled={props.disabled} value={text} onChange={(e) => { setText(e.target.value); props.onChange?.(e.target.value); }} />;
  }) };
});
afterEach(cleanup);
test.each([false, true])("a draft typed during streaming survives completion and can be sent with the chosen intent (new question: %s)", (newQuestion) => {
  const f = new Fixture();
  const sendCapture = vi.fn((capture: { text: string }, _intent: string) => f.send(capture.text));
  const session = { sessionId: SESSION, sendCapture, commands: { get: async () => ({ captures: [] }) }, discardFailed: vi.fn() } as unknown as SessionController;
  render(<LocaleProvider locale="en"><StoreProvider holder={f.holder} session={session}><Composer sessionId={SESSION} /></StoreProvider></LocaleProvider>);
  fireEvent.change(screen.getByRole("textbox", { name: "Message to the tutor" }), { target: { value: "First question." } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  const cli = sendCapture.mock.results[0]!.value as string;
  f.startTurn(cli); f.text("The response is still streaming.", false);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Next draft." } });
  f.end();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Next draft.");
  if (newQuestion) {
    fireEvent.click(screen.getByRole("button", { name: "New question" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Next draft." } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(sendCapture.mock.calls[1]?.[1]).toBe(newQuestion ? "ask" : "answer");
  expect(sendCapture.mock.calls[1]?.[0].text).toBe("Next draft.");
});
