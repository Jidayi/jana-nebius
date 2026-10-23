// Settings (UXS-29, UXS-46, TABLE UXS-46a): the sections the core names, in its order; family settings keep profile
// isolation and use no elevation or adjustable answer policy (D86, D87).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { LocaleProvider } from "../src/i18n.js";
import { FAMILY_GROUPS } from "../src/settings/FamilyControls.js";
import { PREFERENCE_SECTIONS, Settings } from "../src/settings/Settings.js";

const BEN = PROFILES[1]!;
afterEach(cleanup);

async function unlocked(setUp: (core: FakeProfileCore) => void = () => undefined, chooseSource?: (kind: string) => Promise<string | null>) {
  const core = new FakeProfileCore();
  setUp(core);
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(BEN.profile_id)).toBe(true);
  const view = render(<LocaleProvider locale="en"><Settings profiles={profiles} {...(chooseSource !== undefined ? { chooseSource } : {})} /></LocaleProvider>);
  await screen.findByRole("checkbox", { name: "Easy-read text" });
  return { core, profiles, view };
}

/** The section list's names, in order. */
const listed = () => within(screen.getByRole("navigation", { name: "Settings sections" })).getAllByRole("button").map((b) => b.textContent);
/** The section headings on the page, in order. */
const headings = () => [...document.querySelectorAll("[data-settings-section] > h2")].map((h) => h.textContent);

/** TABLE UXS-46a's stage 2 rows, in order, by the names the page gives them. */
const STAGE_2 = ["Online features", "Profiles", "Tutor models", "Content", "What leaves this device", "Accessibility and language", "Study", "Tutor", "Data export", "Licence", "Help", "About"];

describe("UXS-29", () => {
  test("uxs29_no_pin_anywhere", async () => {
    const { core } = await unlocked();
    const token = core.tokenOf(BEN.profile_id)!;
    fireEvent.click(screen.getByRole("checkbox", { name: "Easy-read text" }));
    await waitFor(() => expect(core.settings.get(BEN.profile_id)!.easy_read).toBe(true));
    const preference = core.log.find((r) => r.method === "PATCH" && r.path.endsWith("/settings"))!;
    expect(preference.headers["x-profile-token"]).toBe(token);
    expect(preference.headers["x-adult-token"]).toBeUndefined();
    // Every section is open on the page: the online switches need no reveal, PIN or adult token.
    await screen.findByRole("checkbox", { name: "Downloads" });
    expect(screen.queryByLabelText("Adult PIN")).toBeNull();
    expect(document.body.textContent).not.toMatch(/\bPIN\b/);
    // No answer-policy choice anywhere (D86); the only radios are the student's own Theme (DSN-05), text size (DSN-07)
    // and extra time in mock exams (ASM-24, LOC-24).
    expect(screen.queryAllByRole("radio").filter((r) => !["Theme", "Board and chat text size", "Extra time in mock exams"].includes(r.closest("[role='radiogroup']")?.getAttribute("aria-label") ?? ""))).toHaveLength(0);
    // Switching a feature on asks once and needs nothing more than the launch credential.
    fireEvent.click(screen.getByRole("checkbox", { name: "Downloads" }));
    expect(screen.queryByLabelText(/PIN|code/i)).toBeNull();
    expect(core.log.some((r) => r.path.startsWith("/v1/adult/"))).toBe(false);
    expect(core.log.every((r) => r.headers["x-adult-token"] === undefined)).toBe(true);
  });

  test("uxs29_family_settings", async () => {
    const { core } = await unlocked();
    const preferences = PREFERENCE_SECTIONS.flatMap((s) => s.keys);
    expect(preferences).not.toContain("solution_policy");
    await screen.findByRole("checkbox", { name: "Downloads" });
    // Online features and Profiles are two sections of the page, each with its own heading.
    const groups = [...document.querySelectorAll<HTMLElement>("[data-family-group]")];
    expect(groups.map((g) => g.dataset.familyGroup)).toEqual([...FAMILY_GROUPS]);
    expect(groups.map((g) => g.closest("[data-settings-section]")?.querySelector("h2")?.textContent)).toEqual(["Online features", "Profiles"]);
    const deletes = within(groups[1]!).getAllByRole("button", { name: "Delete profile" }) as HTMLButtonElement[];
    expect(deletes[0]!.disabled).toBe(true); // another profile's data stays scoped to its owner
    expect(deletes[1]!.disabled).toBe(false);
    fireEvent.click(deletes[1]!);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("Delete Ben's profile?");
    expect(document.body.textContent).not.toMatch(/Adult PIN|Never: hints only|PINs stop other students/);
    // No "Answers" section anywhere on the page (D87).
    expect(screen.queryAllByRole("heading").map((h) => h.textContent)).not.toContain("Answers");
    // One confirmation removes the open profile: the dialog's own button, no second prompt and nothing typed.
    expect(within(dialog).queryAllByRole("textbox")).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete profile" }));
    await waitFor(() => expect(core.log.filter((r) => r.method === "DELETE" && r.path === `/v1/profiles/${BEN.profile_id}`)).toHaveLength(1));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("UXS-46", () => {
  test("test_uxs46_settings_page_sections", async () => {
    const { core } = await unlocked();
    // Exactly the sections the core names for this build's stage, in its order, each on the page with its heading.
    await waitFor(() => expect(core.log.some((r) => r.path === "/v1/settings/sections")).toBe(true));
    expect(listed()).toEqual(STAGE_2);
    expect(headings()).toEqual(STAGE_2);
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(within(nav).getByRole("button", { name: "Online features" }).getAttribute("aria-current")).toBe("true");
    fireEvent.click(within(nav).getByRole("button", { name: "Licence" }));
    expect(within(nav).getByRole("button", { name: "Licence" }).getAttribute("aria-current")).toBe("true");
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "Licence" }));
    // Licence: no school licence on a family computer, and nothing to type (PLT-19).
    await screen.findByText(/No school licence is installed/);
    expect(document.querySelector("[data-licence='none']")).not.toBeNull();
    // About: the version from the core and the licences of what the app ships, with the brand (DSN-25), and updates.
    await screen.findByText("0.1.0-fake");
    expect(document.querySelector("[data-about] [data-brand]")).not.toBeNull();
    expect(within(document.querySelector<HTMLElement>("[data-settings-section='about']")!).getByRole("button", { name: "Choose an update from USB or a file" })).toBeTruthy();
    // Tutor models holds the model manager; Content the packs; Tutor the tutor's name; Data export the archive.
    expect(document.querySelector("[data-settings-section='tutor_models'] [data-model-manager]")).not.toBeNull();
    expect(within(document.querySelector<HTMLElement>("[data-settings-section='content']")!).getByRole("button", { name: "Install content from USB or a file" })).toBeTruthy();
    expect(document.querySelector("[data-settings-section='tutor']")!.textContent).toContain("Your tutor is called Jana.");
    expect(document.querySelector("[data-settings-section='data_export'] [data-profile-archive]")).not.toBeNull();
    // Board and chat text size writes the student's text scale (DSN-07).
    const size = screen.getByRole("radiogroup", { name: "Board and chat text size" });
    fireEvent.click(within(size).getByRole("radio", { name: "Largest" }));
    await waitFor(() => expect(core.settings.get(BEN.profile_id)!.text_scale).toBe(1.5));
    // The character-key shortcuts switch (LOC-12) and the keyboard help it describes.
    const keys = screen.getByRole("checkbox", { name: "Character-key shortcuts" });
    expect((keys as HTMLInputElement).checked).toBe(true);
    fireEvent.click(keys);
    expect((screen.getByRole("checkbox", { name: "Character-key shortcuts" }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: "Show keyboard shortcuts" })[0]!);
    const help = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(help.textContent).toContain("Single-key shortcuts are off");
    fireEvent.keyDown(help, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("test_uxs46_stage_3_sections_and_a_core_without_the_route", async () => {
    // A stage 3 core adds Parent summary, Alerts and Voice after About; a section this app has no body for says so.
    await unlocked((core) => { core.sectionsStage = "S3"; });
    await waitFor(() => expect(listed()).toEqual([...STAGE_2, "Parent summary", "Alerts", "Voice"]));
    expect(headings()).toEqual([...STAGE_2, "Parent summary", "Alerts", "Voice"]);
    expect(document.querySelector("[data-settings-section='alerts']")!.textContent).toContain("isn't in this version of the app yet");
    cleanup();
    // A core from before the route: the stage 2 sections, in the table's order.
    const { core } = await unlocked((c) => { c.sectionsStage = null; });
    await waitFor(() => expect(core.log.some((r) => r.path === "/v1/settings/sections")).toBe(true));
    expect(listed()).toEqual(STAGE_2);
  });

  test("test_uxs46_data_export_saves_the_open_profiles_archive", async () => {
    // Data export (DAT-10): the archive needs a passphrase of 12 or more characters and a folder; it is the open
    // profile's, conversations and photos stay out, and the passphrase leaves the field once the core accepts it.
    const { core } = await unlocked(() => undefined, async () => "/synthetic/folder");
    const archive = document.querySelector<HTMLElement>("[data-profile-archive]")!;
    const save = within(archive).getByRole("button", { name: "Save a profile archive" }) as HTMLButtonElement;
    const field = within(archive).getByLabelText("Passphrase for the archive") as HTMLInputElement;
    expect(field.type).toBe("password");
    fireEvent.change(field, { target: { value: "too short" } });
    expect(save.disabled).toBe(true);
    fireEvent.change(field, { target: { value: "synthetic passphrase" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await within(archive).findByText(/being saved in the folder you chose/);
    expect(core.exports.at(-1)).toEqual({ kind: "profile_archive", include_study_sources: false, profile_ids: [BEN.profile_id], passphrase: "synthetic passphrase", destination: { kind: "file", path: "/synthetic/folder" } });
    expect(field.value).toBe("");
    // Help leads to the report for support, which now sits in Data export.
    fireEvent.click(screen.getByRole("button", { name: "Save a report for support (in Data export)" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "Data export" }));
    expect(within(document.querySelector<HTMLElement>("[data-settings-section='data_export']")!).getByRole("button", { name: "Save a report for support" })).toBeTruthy();
  });


  test("help_searches_offline_and_names_this_computer", async () => {
    // Settings → Help from the core's offline help (OPS-23, the M24 Help API): its articles in the student's language
    // from the catalogue (LOC-01, D93), searched here as the student types, a known problem of this version with what
    // to do, this computer's version, channel and device id, and the support contacts. The core is asked once.
    const core = new FakeProfileCore();
    core.knownIssues = [{ issue_id: "ki_synthetic_slow", title_key: "help.synthetic_missing_key", help_article_id: "help.slow",
      affects: { artefact_kind: "app", artefact_id: "jana-desktop", versions: ["0.1.0"] } }];
    const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    await profiles.load();
    expect(await profiles.unlock(BEN.profile_id)).toBe(true);
    render(<LocaleProvider locale="en"><Settings profiles={profiles} /></LocaleProvider>);
    const help = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-offline-help]");
      expect(found).not.toBeNull();
      return found!;
    });
    const articles = () => [...help.querySelectorAll("[data-help-article]")].map((a) => a.getAttribute("data-help-article"));
    expect(articles()).toEqual(["slow", "usb"]);
    // A known problem whose title this version has no words for still says what to do, and opens that article.
    expect(help.querySelector("[data-known-issue]")!.textContent).toContain("Known problem: a problem with this version. What to do: The tutor is slow.");
    fireEvent.click(within(help).getByRole("button", { name: "Open \"The tutor is slow\"" }));
    await waitFor(() => expect(within(help).getByRole("button", { name: "The tutor is slow" }).getAttribute("aria-expanded")).toBe("true"));
    expect(help.textContent).toContain("Open Tutor models and select a smaller model.");
    // Searching looks in the articles' words on this computer (a word of a step finds its article); no match says so.
    fireEvent.change(within(help).getByRole("searchbox", { name: "Search help" }), { target: { value: "usb" } });
    await waitFor(() => expect(articles()).toEqual(["usb"]));
    fireEvent.change(within(help).getByRole("searchbox", { name: "Search help" }), { target: { value: "smaller model" } });
    await waitFor(() => expect(articles()).toEqual(["slow"]));
    expect(core.log.filter((r) => r.path === "/v1/help").length).toBe(1);
    fireEvent.change(within(help).getByRole("searchbox", { name: "Search help" }), { target: { value: "printer" } });
    await within(help).findByText("No help article matches \"printer\". Try another word.");
    // This computer and the support contacts.
    const computer = help.querySelector("[data-help-computer]")!;
    expect(computer.textContent).toContain("0.1.0");
    expect(computer.textContent).toContain("Stable");
    expect(computer.textContent).toContain("dev_synthetic01");
    expect(help.textContent).toContain("No support contact is set up on this computer.");
  });

  test("help on a core without the help route says so and keeps the rest", async () => {
    const core = new FakeProfileCore();
    core.helpServed = false;
    const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    await profiles.load();
    expect(await profiles.unlock(BEN.profile_id)).toBe(true);
    render(<LocaleProvider locale="en"><Settings profiles={profiles} /></LocaleProvider>);
    await screen.findByText("Help articles aren't on this computer yet. Saving a report for support still works.");
    expect(screen.getByRole("heading", { level: 3, name: "Your problem reports" })).toBeTruthy();
  });

  test("test_obs17_crash_report_review", async () => {
    const report = { crash_id: "crh_1", process: "core", kind: "exception", version: "0.1.0", error_type: "ValueError", stack: [], log_tail: ["a line"], detail: {}, hardware_class: "mid", day: 20376 };
    const { core, view } = await unlocked();
    // While crash reports are off nothing is listed, so nothing asks (PLT-18).
    expect(document.querySelector("[data-crash-review]")).toBeNull();
    view.unmount();
    core.features.crash_reports = true;
    core.crashReports.push({ ...report });
    const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    await profiles.load();
    expect(await profiles.unlock(BEN.profile_id)).toBe(true);
    render(<LocaleProvider locale="en"><Settings profiles={profiles} /></LocaleProvider>);
    const row = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-crash-id='crh_1']");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(row.textContent).toContain("Send this report?");
    // The report is shown exactly as it would be sent before anyone decides.
    fireEvent.click(within(row).getByRole("button", { name: "Show exactly what would be sent" }));
    expect(row.querySelector("pre")?.textContent).toContain("\"error_type\": \"ValueError\"");
    fireEvent.click(within(row).getByRole("button", { name: "Don't send" }));
    await waitFor(() => expect(core.crashDecisions).toEqual(["crh_1:dismiss"]));
    await waitFor(() => expect(document.querySelector("[data-crash-review]")).toBeNull());
  });
});

describe("CUR-08", () => {
  test("cur08_tampered_pack_rejected", async () => {
    await unlocked((core) => core.packs.push(
      { pack_id: "pack.phy.o", subject: "physics", level: "O", version: "1.0.0", signature_ok: true, size_bytes: 1000 },
      { pack_id: "pack.chm.o", subject: "chemistry", level: "O", version: "1.0.0", signature_ok: false, size_bytes: 1000 },
    ));
    // Settings → Content names the pack that failed its check, and only that one.
    const damaged = await screen.findByText(/The content pack pack\.chm\.o is damaged or was changed/);
    expect(damaged.closest("[data-settings-section]")?.getAttribute("data-settings-section")).toBe("content");
    expect(screen.queryByText(/pack\.phy\.o/)).toBeNull();
    expect(document.querySelectorAll("[data-family-group]")).toHaveLength(2);
  });
});
