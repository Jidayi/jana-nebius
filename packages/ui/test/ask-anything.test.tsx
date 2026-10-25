// M45.a: Home's one input (UXS-67) and Ask anything's answer (STU-20, D117).
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { EMPTY_ASK, type AskAnswer as Answer, type AskView } from "@jana/client-core";
import { AskAnswer } from "../src/home/AskAnswer.js";
import { Home } from "../src/home/Home.js";
import { LocaleProvider } from "../src/i18n.js";

afterEach(() => cleanup());

const ANSWER: Answer = {
  ask_id: "ask_00000000000000000000000001", question: "Why is the sky blue?", mode: "teach", audience: "under_18", reach: "allow_list",
  steps: [{ kind: "own", count: 1 }, { kind: "trusted", count: 4 }],
  sources: [
    { ref: "own1", kind: "own_source", title: "Light notes", source_id: "src_00000000000000000000000001" },
    { ref: "web1", kind: "web", title: "Why is the sky blue?", url: "https://spaceplace.nasa.gov/blue-sky/", domain: "spaceplace.nasa.gov" },
  ],
  own_excerpts: [{ ref: "own1", text: "Blue light is scattered more." }],
  answer: [
    { text: "Air scatters blue light more than red light.", refs: ["web1", "own1"], supported: true, checked: false },
    { text: "People have wondered about this for ages.", refs: [], supported: false, checked: false },
  ],
  check_question: "Why are sunsets red?",
  explanation: [{ text: "Shorter wavelengths scatter more.", refs: ["web1"], supported: true, checked: false }],
  general_knowledge: true, checked: false, can_switch: false,
};
const answered = (answer: Answer, explained = false): AskView => ({ ...EMPTY_ASK, status: "answered", question: answer.question, answer, explained });

function view(v: AskView, calls: string[] = []) {
  return render(
    <LocaleProvider locale="en">
      <AskAnswer view={v} actions={{ onTutor: () => calls.push("tutor"), onStudy: () => calls.push("study"), onExplain: () => calls.push("explain"),
        onAgain: (o) => calls.push(`again:${o.mode}:${o.reach}`), onSearchWeb: () => calls.push("search-web") }} />
    </LocaleProvider>,
  );
}

describe("STU-20", () => {
  test("web search explains Tavily's data use and waits for the explicit action", () => {
    const calls: string[] = [];
    view({ ...EMPTY_ASK, status: "unavailable", question: "Where is Paris?", reason: "web_permission_required" }, calls);
    expect(screen.getByText(/send this question to Tavily/)).toBeTruthy();
    expect(calls).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Search the web with Tavily" }));
    expect(calls).toEqual(["search-web"]);
  });
  test("the search shows before the answer, citations and the label are on each statement, nothing is checked", () => {
    const calls: string[] = [];
    const { container } = view(answered(ANSWER), calls);
    const steps = container.querySelector("[data-ask-steps]")!;
    expect(steps.textContent).toContain("Looked in your notes: 1 match");
    expect(steps.textContent).toContain("Looked at 4 trusted sources");
    // The search comes before the first statement in reading order.
    const first = container.querySelector("[data-ask-statement]")!;
    expect(steps.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const statements = [...container.querySelectorAll("[data-ask-statement]")];
    expect(statements.map((s) => s.getAttribute("data-ask-statement"))).toEqual(["supported", "general"]);
    expect(statements[0]!.textContent).toContain("[2]");
    expect(statements[1]!.querySelector("[data-general-label]")?.textContent).toBe("General knowledge, not checked against your syllabus or your material");
    expect(container.textContent).not.toMatch(/\bchecked\b(?! against)/i);
    // Teach me: the check question first, the explanation only on request.
    expect(container.textContent).toContain("Why are sunsets red?");
    expect(container.textContent).not.toContain("Shorter wavelengths scatter more.");
    fireEvent.click(screen.getByRole("button", { name: "Show the explanation" }));
    expect(calls).toEqual(["explain"]);
    // Under 18 there are no switches, and nowhere is there a model choice.
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(container.textContent).not.toMatch(/model/i);
    cleanup();
    view(answered(ANSWER, true));
    expect(document.body.textContent).toContain("Shorter wavelengths scatter more.");
  });

  test("a learner of 18 or over may switch to Just explain and the wider web; offline offers the tutor and the study area", () => {
    const calls: string[] = [];
    view(answered({ ...ANSWER, audience: "adult", can_switch: true }), calls);
    fireEvent.click(screen.getByRole("radio", { name: "Just explain" }));
    fireEvent.click(screen.getByRole("radio", { name: "Wider web" }));
    expect(calls).toEqual(["again:explain:allow_list", "again:teach:wider_web"]);
    cleanup();
    const offline: string[] = [];
    view({ ...EMPTY_ASK, status: "unavailable", question: "Why?", reason: "offline" }, offline);
    expect(document.body.textContent).toContain("General questions and making study tools need the online plan. You can still use installed lessons, practice and your saved study tools.");
    fireEvent.click(screen.getByRole("button", { name: "Ask the tutor" }));
    fireEvent.click(screen.getByRole("button", { name: "Study your material" }));
    expect(offline).toEqual(["tutor", "study"]);
  });

  test("a subject question spoken here shows the tutor's spoken reply with Continue in the tutor (VOC-53, D130)", () => {
    const calls: string[] = [];
    view({ ...EMPTY_ASK, status: "spoken", question: "What is the formula for kinetic energy?", route: "tutor", spoken: "What do you already know about kinetic energy?" }, calls);
    expect(screen.getByRole("heading", { name: "What is the formula for kinetic energy?" })).toBeTruthy();
    expect(document.body.textContent).toContain("The tutor answered by voice");
    expect(document.body.textContent).toContain("What do you already know about kinetic energy?");
    fireEvent.click(screen.getByRole("button", { name: "Continue in the tutor" }));
    expect(calls).toEqual(["tutor"]);
    cleanup();
    const material: string[] = [];
    view({ ...EMPTY_ASK, status: "spoken", question: "A long passage", route: "study", spoken: "That looks like material." }, material);
    fireEvent.click(screen.getByRole("button", { name: "Study your material" }));
    expect(material).toEqual(["study"]);
  });
});

describe("UXS-67", () => {
  test("Home leads with one input under Ready to learn, with Upload, Link, Paste and Record above the box", () => {
    const picked: string[] = [];
    render(
      <LocaleProvider locale="en">
        <Home name="Ada" ask={<textarea aria-label="Ask anything, or paste a question" />} answer={<p>the answer</p>}
          materials={{ onUpload: (f) => picked.push(`upload:${f.name}`), onLink: () => picked.push("link"), onPaste: () => picked.push("paste"), onRecord: (f) => picked.push(`record:${f.name}`) }}
          plan={<p data-plan="">Next up</p>} subjects={[]} onSubject={() => undefined} pickup={[]} onPickup={() => undefined}
          practice={{ ideas: [], refreshes: 0, subjectLabel: (s) => s }} onPractice={() => undefined} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Ready to learn, Ada?");
    const group = screen.getByRole("group", { name: "Add material" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["Upload", "Link", "Paste", "Record"]);
    const box = screen.getByRole("textbox", { name: "Ask anything, or paste a question" });
    // Results precede the input; material controls remain directly above it, and the plan follows both.
    expect(group.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("the answer").compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("the answer").compareDocumentPosition(document.querySelector("[data-plan]")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(within(group).getByRole("button", { name: "Link" }));
    fireEvent.click(within(group).getByRole("button", { name: "Paste" }));
    const [upload, record] = [...document.querySelectorAll<HTMLInputElement>("[data-home-materials] input[type=file]")];
    fireEvent.change(upload!, { target: { files: [new File(["x"], "notes.pdf")] } });
    fireEvent.change(record!, { target: { files: [new File(["x"], "lecture.m4a")] } });
    expect(picked).toEqual(["link", "paste", "upload:notes.pdf", "record:lecture.m4a"]);
  });
});
