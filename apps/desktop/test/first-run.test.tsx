// UXS-10, PLT-17, PLT-29, UXS-09 and UXS-14 in the app as it is wired: a computer with no students opens on "Who's
// learning?", which asks for names only and adds each student with TABLE PLT-17b's defaults for the installed packs;
// the hand-off says once what the tutor can do here and is never shown again on a later launch; with no tutor model,
// or below the minimum laptop, the app lands on Learn, offers no Tutor place and Home offers lessons instead of an Ask
// box. The picker adds a student and says when a profile cannot be opened. The tutor's subject is chosen from the
// installed packs and is the one the student last worked on; accounting brings the ledger entry. The navigation names
// Settings and Switch student in words, and the open profile's Easy-read and Reduce motion preferences apply to the
// whole app. Against the fake core, with the gallery's fixtures.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import type { SubjectMap as Map } from "@jana/client-core";
import type { ModelCatalogue } from "@jana/contracts-ts";
import { STATES } from "@jana/ui/gallery";
import { FakeProfileCore, PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { menuItem, findMenuItem } from "./student-menu.js";

const payload = <T,>(id: string) => STATES.find((s) => s.id === id)!.payload as T;
const MAP = payload<{ map: Map }>("subject-map.canonical.topic-sheet").map;
const LESSON = payload<{ lesson: Record<string, unknown> & { lesson_id: string } }>("lesson-player.canonical").lesson;
const TOPIC = MAP.sections[0]!.topics[0]!;
const ADA = PROFILES[0]!;

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-easy-read");
  document.documentElement.removeAttribute("data-reduced-motion");
});

const pack = (subject: string) => ({ pack_id: `pack.${subject}.o`, subject, level: "O" as const, version: "0.1.0", signature_ok: true, size_bytes: 1 });

function core(setup: (core: FakeProfileCore) => void = () => undefined): FakeProfileCore {
  const fake = new FakeProfileCore();
  fake.maps.set(MAP.subject_id, MAP);
  fake.lessons.set(LESSON.lesson_id, LESSON);
  fake.packs.push(pack("phy"), pack("acc"));
  setup(fake);
  return fake;
}

function start(fake: FakeProfileCore) {
  const runtime = createRuntime(fake.launch, fake.fetch);
  render(<App runtime={runtime} />);
  return runtime;
}

const posts = (fake: FakeProfileCore, path: string) => fake.log.filter((r) => r.method === "POST" && r.path === path).map((r) => r.body as Record<string, unknown>);

async function firstRun(names: string[]) {
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.change(screen.getByRole("textbox", { name: "First name or nickname" }), { target: { value: names[0] } });
  for (const name of names.slice(1)) {
    fireEvent.click(screen.getByRole("button", { name: "Add another student" }));
    const fields = screen.getAllByRole("textbox", { name: "Another student's first name or nickname" });
    fireEvent.change(fields.at(-1)!, { target: { value: name } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Start learning" }));
  return screen.findByRole("region", { name: `You're ready, ${names[0]}.` });
}

async function mapTile() {
  return waitFor(() => {
    const found = document.querySelector<HTMLButtonElement>(`[data-topic-id="${TOPIC.node_id}"]`);
    expect(found).not.toBeNull();
    return found!;
  });
}

describe("UXS-10 and PLT-17", () => {
  test("uxs10_step_order_matches_plt17", async () => {
    const fake = core((c) => c.profiles.splice(0));
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    // One step: a name, "Add another student", the privacy line and "Start learning". Nothing else is asked.
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(document.body.textContent).toContain("Everything stays on this computer unless you turn on online features later.");
    expect(document.body.textContent).not.toMatch(/PIN|recovery code|Step \d of \d/);
    // In a short or narrow window the card scrolls inside its own area, above the status line at the foot of the
    // screen, instead of spilling over it ("On this computer" never covers "Start learning").
    const area = screen.getByRole("button", { name: "Start learning" }).closest<HTMLElement>("[data-centred]")!;
    expect(area.className).toMatch(/\boverflow-y-auto\b/);
    expect(area.contains(screen.getByRole("complementary", { name: "Status" }))).toBe(false);
    const handoff = await firstRun(["Ada", "Ben"]);
    // Each student added with TABLE PLT-17b's defaults: the installed subjects at their level, the minor age band.
    expect(posts(fake, "/v1/profiles")).toEqual([
      { display_name: "Ada", avatar: "avatar-1", level: "O", subjects: ["physics", "accounting"], age_band: "13_15" },
      { display_name: "Ben", avatar: "avatar-2", level: "O", subjects: ["physics", "accounting"], age_band: "13_15" },
    ]);
    expect(handoff.textContent).not.toMatch(/Step \d of \d/);
    fireEvent.click(within(handoff).getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Ask a question" }); // Home follows the hand-off
    cleanup();

    // A later launch: the picker, and the hand-off is not said again.
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    fireEvent.click(screen.getByRole("button", { name: /^Ben/ }));
    await screen.findByRole("navigation", { name: "Main" });
    expect(screen.queryByRole("region", { name: /You're ready/ })).toBeNull();
  });

  test("uxs10_below_minimum_laptop_state", async () => {
    const fake = core((c) => {
      c.profiles.splice(0);
      c.models = payload<ModelCatalogue>("first-run-tutor.canonical.below-minimum");
      c.health = { status: "ok", components: { core: "ok", runtime: "down" }, readiness: "core_ready" };
    });
    start(fake);
    const handoff = await firstRun(["Ada"]);
    await waitFor(() => expect(handoff.textContent).toContain("This computer has 4 GB of memory; the tutor needs 8 GB."));
    expect(handoff.textContent).toContain("Lessons, practice and worked solutions work here.");
    expect(handoff.textContent).not.toMatch(/an adult/i);
    expect(within(handoff).getByRole("button", { name: "Online features" })).toBeTruthy();
    fireEvent.click(within(handoff).getByRole("button", { name: "Continue without the tutor" }));
    // It goes on to Learn, in the content-only class: no Tutor place and no screen offers the tutor.
    const tile = await mapTile();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("button", { name: "Tutor" })).toBeNull();
    expect(within(nav).queryByRole("button", { name: "New question" })).toBeNull(); // nothing opens a tutor that cannot reply
    fireEvent.click(tile);
    const sheet = await screen.findByRole("dialog", { name: TOPIC.title });
    expect(within(sheet).queryByRole("button", { name: "Ask the tutor about this" })).toBeNull();
  });
});

/** What the app sent that changes something (every request but a read). */
const writes = (fake: FakeProfileCore) => fake.log.filter((r) => r.method !== "GET").map((r) => `${r.method} ${r.path}`);

describe("PLT-17 and UXS-10, offline and minimal", () => {
  test("plt17_minimal_first_run", async () => {
    const fake = core((c) => c.profiles.splice(0));
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    // Nothing but a name is asked: no secret, code, licence or account field, and no word for one.
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(document.querySelector("input[type='password'], input[autocomplete^='cc-'], select")).toBeNull();
    expect(document.body.textContent).not.toMatch(/\bPIN\b|recovery code|activation|licen[cs]e|account|sign in|password/i);
    // The step's actions (TABLE PLT-17a), then the connection status at the foot that says everything stays here.
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Add another student", "Start learning", "On this computer"]);
    const handoff = await firstRun(["Ada"]);
    expect(handoff.textContent).not.toMatch(/\bPIN\b|recovery code|activation|licen[cs]e|account|sign in|password/i);
    // "Start learning" after one name: one student added with TABLE PLT-17b's defaults and the step recorded as done
    // (`PUT /v1/setup`, so a later launch opens the picker), and nothing else written.
    // No licence, setting, online feature or consent was touched (every online feature stays off).
    expect(posts(fake, "/v1/profiles")).toEqual([{ display_name: "Ada", avatar: "avatar-1", level: "O", subjects: ["physics", "accounting"], age_band: "13_15" }]);
    const created = fake.profiles[0]!.profile_id;
    for (const write of writes(fake)) expect(write, write).toMatch(new RegExp(`^POST /v1/profiles(/${created}/(open|unlock))?$|^POST /v1/sessions|^PUT /v1/setup$`));
    await waitFor(() => expect(writes(fake)).toContain("PUT /v1/setup"));
    expect(fake.log.some((r) => r.path.startsWith("/v1/licence"))).toBe(false);
    expect(Object.values(fake.features).some(Boolean)).toBe(false);
  });

  test("uxs10_offline_first_run", async () => {
    // Networking disabled (every online feature off, as on a fresh install): first run ends with each tutor state the
    // bundled or USB models leave, and no screen on the way offers a download or asks for one.
    const fixtures = ["first-run-tutor.canonical", "first-run-tutor.canonical.no-model", "first-run-tutor.canonical.content-only", "first-run-tutor.canonical.below-minimum"];
    for (const id of fixtures) {
      const fake = core((c) => {
        c.profiles.splice(0);
        c.models = payload<ModelCatalogue>(id);
        if (id !== "first-run-tutor.canonical") c.health = { status: "ok", components: { core: "ok", runtime: "down" }, readiness: "core_ready" };
      });
      expect(fake.network, id).toBeNull();
      start(fake);
      await screen.findByRole("heading", { name: "Who's learning?" });
      expect(document.body.textContent, id).not.toMatch(/download/i);
      const handoff = await firstRun(["Ada"]);
      await waitFor(() => expect(handoff.getAttribute("data-setup"), id).not.toBe("checking"));
      expect(document.body.textContent, id).not.toMatch(/download/i);
      for (const button of within(handoff).getAllByRole("button")) expect(button.textContent, id).not.toMatch(/download|get the tutor|buy|subscribe/i);
      expect(fake.log.filter((r) => /download/.test(r.path)), id).toEqual([]);
      expect(fake.log.filter((r) => r.path === "/v1/packs/install"), id).toEqual([]);
      cleanup();
    }
  });
});

describe("PLT-29", () => {
  test("test_plt29_no_tutor_model_lands_on_learn", async () => {
    const fake = core((c) => {
      c.models = { ...c.models, installed: [] };
      c.health = { status: "ok", components: { core: "ok", runtime: "down" }, readiness: "core_ready" };
    });
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
    await mapTile(); // Learn, not a tutor that cannot answer
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("button", { name: "Tutor" })).toBeNull();
    expect(within(nav).queryByRole("button", { name: "New question" })).toBeNull(); // nothing opens a tutor that cannot reply
    fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
    // Home offers lessons instead of an Ask box, with the PLT-17 words for no tutor model.
    await screen.findByText("No tutor model is installed yet. You can start lessons and practice now and add the tutor later from Settings or a USB drive.");
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Browse topics" }));
    await mapTile();
  });
});

describe("UXS-10 resume and UXS-47", () => {
  test("test_uxs10_resume_at_the_same_step", async () => {
    // First run was left part way: two students were added, "Start learning" was never pressed.
    const fake = core((c) => {
      c.profiles.splice(2);
      c.setupDone = false;
    });
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    const added = screen.getByRole("list", { name: "Students already added" });
    expect(within(added).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["AAda", "BBen"]);
    // Nothing more needs typing: "Start learning" opens the first student and records the step as done.
    fireEvent.click(screen.getByRole("button", { name: "Start learning" }));
    await screen.findByRole("region", { name: "You're ready, Ada." });
    await waitFor(() => expect(fake.log.some((r) => r.method === "PUT" && r.path === "/v1/setup")).toBe(true));
    expect(posts(fake, "/v1/profiles")).toEqual([]); // nobody was added twice
  });

  test("uxs47_restore_reachable", async () => {
    const fake = core((c) => c.unavailable.add("/v1/profiles"));
    const runtime = createRuntime(fake.launch, fake.fetch);
    runtime.chooseArchive = async () => "/media/usb/ada.janaprofile";
    render(<App runtime={runtime} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Profiles couldn't be opened. Your data is still on this computer.");
    fireEvent.click(within(alert).getByRole("button", { name: "Show recovery options" }));
    await screen.findByRole("heading", { name: "Let's get your profiles back" });
    fireEvent.click(screen.getByRole("button", { name: "Restore from a profile archive" }));
    fireEvent.change(await screen.findByLabelText("The archive's passphrase"), { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: "Restore from a profile archive" }));
    await screen.findByText("The profile is back. Choose it to carry on.");
    expect(fake.imports).toEqual([{ source: { kind: "file", path: "/media/usb/ada.janaprofile" }, passphrase: "correct horse" }]);
    // No dead end: back to the profiles, which open again once the store reads.
    fake.unavailable.clear();
    fireEvent.click(screen.getByRole("button", { name: "Go to the profiles" }));
    await screen.findByRole("heading", { name: "Who's learning?" });
  });
});

describe("UXS-09", () => {
  test("test_uxs09_add_student_from_the_picker", async () => {
    const fake = core();
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    fireEvent.click(screen.getByRole("button", { name: "Add student" }));
    fireEvent.change(screen.getByRole("textbox", { name: "First name or nickname" }), { target: { value: "Dee" } });
    fireEvent.click(screen.getByRole("button", { name: "Add student" }));
    await screen.findByRole("button", { name: /^Dee/ });
    expect(posts(fake, "/v1/profiles").at(-1)).toEqual({ display_name: "Dee", avatar: "avatar-4", level: "O", subjects: ["physics", "accounting"], age_band: "13_15" });
  });

  test("test_uxs09_open_failure_is_said", async () => {
    const fake = core((c) => c.unavailable.add(`/v1/profiles/${ADA.profile_id}/open`));
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Ada's profile couldn't be opened. Its files are still on this computer.");
    fake.unavailable.clear();
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await screen.findByRole("navigation", { name: "Main" });
  });
});

describe("UXS-14", () => {
  test("test_uxs14_tutor_subject_from_installed_packs_and_remembered", async () => {
    const fake = core();
    const runtime = start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
    // Home (the hub, UXS-01) offers the installed subjects beside the Ask box; the first is chosen to start with.
    const subjects = await screen.findByRole("group", { name: "Choose a subject" });
    expect(within(subjects).getAllByRole("button").map((b) => b.textContent)).toEqual(["Physics", "Accounting"]);
    await waitFor(() => expect(posts(fake, "/v1/sessions").at(-1)).toMatchObject({ subject: "physics", level: "O" }));
    await waitFor(() => expect(within(subjects).getByRole("button", { name: "Physics" }).getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(within(subjects).getByRole("button", { name: "Accounting" }));
    await waitFor(() => expect(posts(fake, "/v1/sessions").at(-1)).toMatchObject({ subject: "accounting", level: "O" }));
    // The accounting session brings the ledger entry with it.
    await waitFor(() => expect(runtime.holder.getState().sessions[ADA.session_id]?.subject).toBe("accounting"));

    // Switching student and back: Home opens on accounting again, continuing the same session.
    const made = posts(fake, "/v1/sessions").length;
    fireEvent.click(menuItem("Switch student"));
    await screen.findByRole("heading", { name: "Who's learning?" });
    fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
    const again = await screen.findByRole("group", { name: "Choose a subject" });
    await waitFor(() => expect(within(again).getByRole("button", { name: "Accounting" }).getAttribute("aria-pressed")).toBe("true"));
    expect(posts(fake, "/v1/sessions")).toHaveLength(made);
  });
});

describe("UXS-01, LOC-18 and LOC-20", () => {
  test("test_uxs01_settings_and_switch_student_are_named_in_words", async () => {
    start(core());
    await screen.findByRole("heading", { name: "Who's learning?" });
    fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
    const nav = await screen.findByRole("navigation", { name: "Main" });
    // Both in the student menu, behind the student's row (D115), named in words.
    expect(within(nav).getByRole("button", { name: "Ada, student menu" })).toBeTruthy();
    expect(menuItem("Settings").textContent).toMatch(/^Settings/);
    expect(menuItem("Switch student").textContent).toBe("Switch student");
  });

  test("test_loc18_saved_preferences_apply_to_the_app", async () => {
    const fake = core((c) => Object.assign(c.settings.get(ADA.profile_id)!, { easy_read: true, reduced_motion: true, text_scale: 1.3 }));
    start(fake);
    await screen.findByRole("heading", { name: "Who's learning?" });
    // Before a profile opens the app follows this computer's theme (DSN-05).
    expect(document.documentElement.getAttribute("data-theme")).toMatch(/^(light|dark)$/);
    fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
    await waitFor(() => expect(document.documentElement.getAttribute("data-easy-read")).toBe("true"));
    expect(document.documentElement.getAttribute("data-reduced-motion")).toBe("true");
    // Board and chat text size (DSN-07, LOC-17) scales body text through --text-scale.
    expect(document.documentElement.style.getPropertyValue("--text-scale")).toBe("1.3");
    fireEvent.click(await findMenuItem("Switch student"));
    await screen.findByRole("heading", { name: "Who's learning?" });
    await waitFor(() => expect(document.documentElement.hasAttribute("data-easy-read")).toBe(false));
    expect(document.documentElement.hasAttribute("data-reduced-motion")).toBe(false);
    expect(document.documentElement.style.getPropertyValue("--text-scale")).toBe("");
  });
});

const QUESTION = (prompt: string, labels: string[], multi: boolean) => ({
  card_type: "question", prompt, multi, allow_free_text: multi,
  options: labels.map((label, n) => ({ id: `opt_${n}`, label, recommended: false })),
});

describe("UXS-10 hand-off interview and the shared lab (JRN-03 step 3, D102)", () => {
  test("test_uxs10_interview_follows_the_handoff", async () => {
    const fake = core((c) => {
      c.profiles.splice(0);
      c.interview = [
        { question_id: "goals", card: QUESTION("What would you most like help with?", ["Getting ready for my exams", "Catching up"], true) },
        { question_id: "confidence", card: QUESTION("How confident do you feel about physics right now?", ["Very confident", "Not very confident"], false) },
      ];
    });
    start(fake);
    const handoff = await firstRun(["Ada"]);
    fireEvent.click(within(handoff).getByRole("button", { name: "Continue" }));
    const card = await screen.findByRole("region", { name: "Two quick questions" });
    expect(card.textContent).toContain("Question 1 of 2");
    expect(card.textContent).toContain("What would you most like help with?");
    fireEvent.click(within(card).getByRole("button", { name: "Getting ready for my exams" }));
    fireEvent.click(within(card).getByRole("button", { name: "Send answer" })); // one Send for the picks and own words
    await waitFor(() => expect(fake.interviewAnswers.map((a) => a.question_id)).toEqual(["goals"]));
    await waitFor(() => expect(screen.getByRole("region", { name: "Two quick questions" }).textContent).toContain("Question 2 of 2"));
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    await screen.findByRole("heading", { name: "Ask a question" }); // Home follows; nothing waits for the tutor
    await waitFor(() => expect(fake.interviewAnswers.map((a) => [a.question_id, a.answer.skipped ?? false])).toEqual([["goals", false], ["confidence", true]]));
    expect(fake.interviewAnswers[0]!.answer).toEqual({ option_ids: ["opt_0"] });
  });

  test("test_uxs10_interview_opens_with_the_tutor_pick", async () => {
    // UXS-54: where the core keeps the tutor's character and name, the interview opens with the one pick; a choice is
    // one settings patch, "Keep Jana" saves nothing, and the questions follow either way.
    const withPick = () => core((c) => {
      c.profiles.splice(0);
      for (const s of c.settings.values()) Object.assign(s, { tutor_name: "Jana", tutor_avatar: "avatar.jana" });
      c.interview = [{ question_id: "goals", card: QUESTION("What would you most like help with?", ["Getting ready for my exams", "Catching up"], true) }];
    });
    const tutorPatches = (fake: FakeProfileCore) => fake.log.filter((r) => r.method === "PATCH" && r.path.endsWith("/settings"))
      .map((r) => r.body as Record<string, unknown>).filter((b) => "tutor_avatar" in b || "tutor_name" in b);
    const fake = withPick();
    start(fake);
    fireEvent.click(within(await firstRun(["Ada"])).getByRole("button", { name: "Continue" }));
    const pick = await screen.findByRole("region", { name: "Choose your tutor" });
    fireEvent.click(await within(pick).findByRole("radio", { name: "Orbit" }));
    expect((within(pick).getByRole("textbox", { name: "Your tutor's name" }) as HTMLInputElement).value).toBe("Orbit");
    fireEvent.click(within(pick).getByRole("button", { name: "Choose this tutor" }));
    await screen.findByRole("region", { name: "Two quick questions" });
    expect(tutorPatches(fake)).toEqual([{ tutor_avatar: "avatar.orbit", tutor_name: "Orbit" }]);
    cleanup();

    const kept = withPick();
    start(kept);
    fireEvent.click(within(await firstRun(["Ada"])).getByRole("button", { name: "Continue" }));
    fireEvent.click(within(await screen.findByRole("region", { name: "Choose your tutor" })).getAllByRole("button", { name: "Keep Jana" })[0]!);
    await screen.findByRole("region", { name: "Two quick questions" });
    expect(tutorPatches(kept)).toEqual([]);
  });

  test.each(["light", "dark"] as const)("uxs09_lab_notice_shown: %s family and school picker", async (theme) => {
    for (const installKind of ["school_lab", "family"] as const) {
      const fake = core((c) => {
        c.licence = { ...c.licence, state: "active", install_kind: installKind, licence_id: "lic-test", seats: 30 };
      });
      start(fake);
      await screen.findByRole("heading", { name: "Who's learning?" });
      document.documentElement.dataset.theme = theme;
      if (installKind === "school_lab") {
        await screen.findByText(/This is a shared computer\. Anyone who uses it can open your profile/);
        expect(document.body.textContent).toContain("they are not locked");
      } else await waitFor(() => expect(screen.queryByText(/This is a shared computer/)).toBeNull());
      expect(document.documentElement.dataset.theme).toBe(theme);
      expect(screen.queryByLabelText(/pin|recovery code/i)).toBeNull();
      expect(document.querySelector('input[type="password"], input[autocomplete="one-time-code"]')).toBeNull();
      cleanup();
    }
    delete document.documentElement.dataset.theme;
  });
});
