// M45.a in the app as it is wired: Home's one box routes by content (UXS-67). A problem in an installed subject goes to
// the tutor, a pasted passage to the study area, and a general question to Ask anything, whose answer shows under the
// box; offline, Ask anything says general questions need the online plan and offers the tutor (STU-20). Against the fake core.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { StrictMode } from "react";
import { App, createRuntime } from "../src/App.js";

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({
  matches: true, media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined,
  addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
})));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const ANSWER = {
  ask_id: "ask_00000000000000000000000001", question: "What is the capital of France?", mode: "teach", audience: "under_18", reach: "allow_list",
  steps: [{ kind: "own", count: 0 }, { kind: "trusted", count: 1 }],
  sources: [{ ref: "web1", kind: "web", title: "Paris | Britannica", url: "https://www.britannica.com/place/Paris", domain: "britannica.com" }],
  own_excerpts: [], answer: [{ text: "Paris is the capital of France.", refs: ["web1"], supported: true, checked: false }],
  check_question: "Why might a capital grow up beside a river?", explanation: [], general_knowledge: false, checked: false, can_switch: false,
};
const PASSAGE = "The Niger is the main river of West Africa. It rises in the Guinea Highlands and flows through Mali, Niger and Nigeria. "
  + "Its delta is one of the largest wetlands in Africa. Many towns grew up along its banks, and fishing and farming depend on its yearly flood. "
  + "Dams built in the twentieth century changed the flood. Today the river supplies water, power and food to millions of people.";

function routed(online: boolean) {
  const core = new FakeProfileCore();
  core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  const asked: { path: string; body: { question?: string; text?: string } }[] = [];
  const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });
  const fetcher = (async (input, init = {}) => {
    const url = new URL(String(input));
    if (url.pathname === "/v1/meta") {
      const meta = await (await core.fetch(input, init)).json() as { capabilities: string[] };
      return json({ ...meta, capabilities: [...meta.capabilities, "study_workspace"] });
    }
    if (!url.pathname.startsWith("/v1/ask")) return core.fetch(input, init);
    const body = JSON.parse(String(init.body ?? "{}"));
    asked.push({ path: url.pathname, body });
    const text: string = body.text ?? body.question ?? "";
    const route = /m\/s|accelerat/.test(text) ? { route: "tutor", reason: "problem_in_subject", subject: "physics" }
      : text.length > 300 ? { route: "study", reason: "material" } : { route: "ask", reason: "general" };
    if (url.pathname === "/v1/ask/route") return json({ ...route, ask: online ? { available: true } : { available: false, reason: "offline" } });
    if (route.route !== "ask") return json({ ...route, answer: null });
    return json(online ? { route: "ask", state: "answered", answer: { ...ANSWER, question: text } } : { route: "ask", state: "unavailable", reason: "offline", answer: null });
  }) as typeof fetch;
  return { core, fetch: fetcher, asked };
}

async function home(fake: ReturnType<typeof routed>) {
  render(<App runtime={createRuntime(fake.core.launch, fake.fetch)} />);
  fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
  const nav = await screen.findByRole("navigation", { name: "Main" });
  await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
  await screen.findByRole("group", { name: "Add material" });
  return nav;
}

async function type(text: string) {
  const box = await waitFor(() => {
    const found = document.querySelector<HTMLElement>("[contenteditable='true']");
    expect(found).not.toBeNull();
    return found!;
  });
  fireEvent.paste(box, { clipboardData: { getData: (kind: string) => (kind === "text/plain" ? text : "") } });
  await waitFor(() => expect(box.textContent).toContain(text.slice(0, 20)));
  fireEvent.keyDown(box, { key: "Enter" });
}

const turns = (fake: ReturnType<typeof routed>) => fake.core.log.filter((r) => r.method === "POST" && /\/turns$/.test(r.path));

describe("UXS-67", () => {
  test("uxs67_one_input_routes", async () => {
    const fake = routed(true);
    const nav = await home(fake);
    // A general question: Ask anything answers under the box; nothing goes to the tutor.
    await type("What is the capital of France?");
    await screen.findByText("Looked at 1 trusted source");
    expect(screen.getByText("Paris is the capital of France.")).toBeTruthy();
    expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBe("page");
    expect(turns(fake)).toHaveLength(0);
    expect(fake.asked.map((a) => a.path)).toEqual(["/v1/ask/route", "/v1/ask"]);
    // A syllabus problem: the tutor opens with it, and Ask anything is never asked.
    await type("A car accelerates from rest to 20 m/s in 5 s. What is its acceleration?");
    await waitFor(() => expect(turns(fake)).toHaveLength(1));
    await waitFor(() => expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBeNull());
    expect(fake.asked.filter((a) => a.path === "/v1/ask")).toHaveLength(1);
    // A pasted passage: the study area opens with it added as material.
    fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    await type(PASSAGE);
    await waitFor(() => expect(fake.core.log.some((r) => r.method === "POST" && /^\/v1\/study\/(sources|retries\/)/.test(r.path))).toBe(true));
    await waitFor(() => expect(within(nav).getByRole("button", { name: "My materials" }).getAttribute("aria-current")).toBe("page"));
    expect(turns(fake)).toHaveLength(1);
  });

  test("offline, a general question says it needs the online plan and Ask the tutor sends it there", async () => {
    const fake = routed(false);
    const nav = await home(fake);
    await type("Who wrote Things Fall Apart?");
    await screen.findByText("General questions and making study tools need the online plan. You can still use installed lessons, practice and your saved study tools.");
    expect(turns(fake)).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Ask the tutor" }));
    await waitFor(() => expect(turns(fake)).toHaveLength(1));
    await waitFor(() => expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBeNull());
  });
});

test.each(["Upload", "Record"])("Home %s enters Study before any file is selected or read", async (action) => {
  const fake = routed(true), runtime = createRuntime(fake.core.launch, fake.fetch);
  const upload = vi.spyOn(runtime.studyWorkspace, "upload").mockResolvedValue();
  render(<StrictMode><App runtime={runtime} /></StrictMode>);
  fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
  const homeActions = await screen.findByRole("group", { name: "Add material" });
  fireEvent.click(within(homeActions).getByRole("button", { name: action }));
  await screen.findByRole("heading", { level: 1, name: "Study" });
  expect(upload).not.toHaveBeenCalled();
  const input = screen.getByLabelText("Choose a file to upload") as HTMLInputElement;
  expect(input.isConnected).toBe(true);
  expect(input.classList.contains("sr-only")).toBe(false);
  expect(input.accept).toContain(action === "Record" ? "audio/*" : ".pdf");
  const file = new File(["personal handwritten notes"], action === "Record" ? "notes.m4a" : "my-notes.pdf");
  const activity = vi.spyOn(runtime.profiles, "noteActivity");
  fireEvent.change(input, { target: { files: [file] } });
  expect(activity).toHaveBeenCalled();
  await waitFor(() => expect(upload).toHaveBeenCalledExactlyOnceWith(file, undefined, true));
});
