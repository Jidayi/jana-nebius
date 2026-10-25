import { expect, test } from "vitest";
import { AskController, EMPTY_ASK, readAnswer, readAskReply, readRoute, readVoiceAnswer, type AskAnswer } from "../src/ask-anything.js";
import { ProfileController } from "../src/profiles.js";
import { StoreHolder } from "../src/session.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

export const ANSWER: AskAnswer = {
  ask_id: "ask_00000000000000000000000001", question: "What is the capital of France?", mode: "teach", audience: "under_18", reach: "allow_list",
  steps: [{ kind: "own", count: 0 }, { kind: "trusted", count: 1 }],
  sources: [{ ref: "web1", kind: "web", title: "Paris | Britannica", url: "https://www.britannica.com/place/Paris", domain: "britannica.com" }],
  own_excerpts: [],
  answer: [{ text: "Paris is the capital of France.", refs: ["web1"], supported: true, checked: false }, { text: "It has been for centuries.", refs: [], supported: false, checked: false }],
  check_question: "Why might a capital grow up beside a river?",
  explanation: [{ text: "Rivers carried trade.", refs: ["web1"], supported: true, checked: false }],
  general_knowledge: true, checked: false, can_switch: false,
};

function askCore(replies: Record<string, unknown>) {
  const core = new FakeProfileCore(), sent: { path: string; body: unknown }[] = [];
  const fetcher = (async (input, init = {}) => {
    const url = new URL(String(input));
    if (!url.pathname.startsWith("/v1/ask")) return core.fetch(input, init);
    const body = init.body ? JSON.parse(String(init.body)) : {};
    sent.push({ path: url.pathname, body });
    const reply = replies[url.pathname];
    return reply instanceof Response ? reply : new Response(JSON.stringify(reply), { status: 200 });
  }) as typeof fetch;
  return { core, fetch: fetcher, sent };
}
test("Tavily confirmation applies only to the current question and preserves the requested mode and reach", async () => {
  const replies: Record<string, unknown> = { "/v1/ask": { route: "ask", state: "unavailable", reason: "web_permission_required", answer: null } };
  const fake = askCore(replies), profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const ask = new AskController(profiles);
  await ask.ask("What is the capital of France?", { mode: "explain", reach: "wider_web" });
  expect(fake.sent).toHaveLength(1);
  expect(fake.sent[0]!.body).toEqual({ question: "What is the capital of France?", mode: "explain", reach: "wider_web" });
  replies["/v1/ask"] = { route: "ask", state: "answered", answer: ANSWER };
  await ask.confirmWeb();
  expect(fake.sent[1]!.body).toEqual({ question: "What is the capital of France?", mode: "explain", reach: "wider_web", web_confirmed: true });
  await ask.ask("Where is the Seine?");
  expect(fake.sent[2]!.body).toEqual({ question: "Where is the Seine?" });
  const count = fake.sent.length;
  await profiles.lock();
  await ask.confirmWeb();
  expect(fake.sent).toHaveLength(count);
});

test("a reply's citations, labels and checks are read under the client's own rules", () => {
  const claimed = { ...ANSWER, general_knowledge: false, checked: true,
    answer: [{ text: "Paris.", refs: ["web1", "web9"], supported: true, checked: true }, { text: "Old city.", refs: ["web9"], supported: true, checked: true }] };
  const read = readAnswer(claimed);
  expect(read.answer.map((s) => [s.refs, s.supported, s.checked])).toEqual([[["web1"], true, false], [[], false, false]]);
  expect(read.general_knowledge).toBe(true);
  expect(read.checked).toBe(false);
  expect(() => readAnswer({ ...ANSWER, check_question: null })).toThrow(); // Teach me always ends with a check question
  expect(readAnswer({ ...ANSWER, sources: [{ ...ANSWER.sources[0]!, url: "http://x.example" }] }).answer[0]!.supported).toBe(false);
  expect(readRoute({ route: "tutor", reason: "problem_in_subject", subject: "physics", ask: { available: true } }).subject).toBe("physics");
  expect(() => readRoute({ route: "tutor", reason: "x", ask: { available: true } })).toThrow();
  expect(readAskReply({ route: "tutor", reason: "installed_subject", subject: "physics", answer: null })).toEqual({ route: "tutor", reason: "installed_subject", subject: "physics" });
  expect(() => readAskReply({ route: "tutor", reason: "installed_subject", answer: ANSWER })).toThrow(); // homework never carries an answer
});

test("asking shows the answer, the offline state, and is cleared with the profile", async () => {
  const fake = askCore({ "/v1/ask": { route: "ask", state: "answered", answer: ANSWER }, "/v1/ask/route": { route: "ask", reason: "general", ask: { available: true } } });
  const profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const ask = new AskController(profiles);
  expect((await ask.route("What is the capital of France?"))?.route).toBe("ask");
  await ask.ask("What is the capital of France?", { mode: "explain" });
  expect(ask.getView()).toMatchObject({ status: "answered", explained: false });
  expect(fake.sent.at(-1)).toEqual({ path: "/v1/ask", body: { question: "What is the capital of France?", mode: "explain" } });
  ask.explain(); expect(ask.getView().explained).toBe(true);
  await profiles.unlock(PROFILES[1]!.profile_id);
  expect(ask.getView()).toEqual(EMPTY_ASK);

  const offline = askCore({ "/v1/ask": { route: "ask", state: "unavailable", reason: "offline", answer: null } });
  const p2 = new ProfileController(offline.core.launch, new StoreHolder(), { fetch: offline.fetch });
  await p2.load(); await p2.unlock(PROFILES[0]!.profile_id);
  const a2 = new AskController(p2);
  await a2.ask("Who wrote Things Fall Apart?");
  expect(a2.getView()).toMatchObject({ status: "unavailable", reason: "offline", answer: null });
});

test("a question spoken in Ask anything shows its answer, or the tutor's spoken reply with Continue (VOC-53, D130)", async () => {
  const fake = askCore({});
  const profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  const ask = new AskController(profiles);
  const base = { type: "voice.answer" as const, place: "ask" as const, turn_id: "trn_01JZ0000000000000000000001", aid_id: null };
  const event = readVoiceAnswer({ ...base, question: "What is the formula for kinetic energy?", route: "tutor", reply: null, text: "What do you already know about it?" });
  expect(event).not.toBeNull();
  ask.voiced(event!);
  expect(ask.getView()).toMatchObject({ status: "spoken", route: "tutor", question: "What is the formula for kinetic energy?", spoken: "What do you already know about it?" });
  ask.voiced({ ...base, question: "What is the capital of France?", route: "ask", reply: { route: "ask", state: "answered", answer: ANSWER }, text: "Paris is the capital of France." });
  expect(ask.getView()).toMatchObject({ status: "answered", question: "What is the capital of France?" });
  ask.voiced({ ...base, question: "Who wrote it?", route: "ask", reply: { route: "ask", state: "unavailable", reason: "offline", answer: null }, text: "General questions need the online plan." });
  expect(ask.getView()).toMatchObject({ status: "unavailable", reason: "offline" });
  ask.voiced({ ...base, question: "How do I make a bomb?", route: "ask", reply: { route: "ask", state: "failed", reason: "safety_template", answer: null }, text: "I can't help with that." });
  expect(ask.getView()).toMatchObject({ status: "blocked", reason: "safety_template" });
  ask.voiced({ ...base, question: "Garbled", route: "ask", reply: { route: "ask", state: "answered", answer: { nope: true } }, text: "x" });
  expect(ask.getView().status).toBe("failed"); // an answer the client cannot read is never shown
  ask.voiced({ ...base, place: "study", question: "Q", route: "study", reply: null, text: "x" });
  expect(ask.getView().status).toBe("failed"); // a study chat's answer is not Ask anything's
  expect(readVoiceAnswer({ type: "voice.caption" })).toBeNull();
});
