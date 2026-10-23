// M23's UI pieces in Settings, over the fake core: the study screen's research consents below the online features
// (PRV-06, D87: on a profile under 18 "Turn on" waits for the parent or guardian's agreement; any profile pauses and
// resumes its own consent with no guardian step), the research export with the study host's approvals and the student's
// assent (EVL-22, `CreateExport.research_approval`), and what a usage report holds, read from the published schema in
// "What leaves this device" (OBS-20, PRV-09).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { LocaleProvider } from "../src/i18n.js";
import { Settings } from "../src/settings/Settings.js";

const BEN = PROFILES[1]!;
afterEach(cleanup);

async function family(adult = false) {
  const core = new FakeProfileCore();
  if (adult) core.adults.add(BEN.profile_id);
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(BEN.profile_id)).toBe(true);
  const chosen: string[] = [];
  render(<LocaleProvider locale="en"><Settings profiles={profiles} chooseSource={async (kind) => { chosen.push(kind); return "/synthetic/study-folder"; }} /></LocaleProvider>);
  await screen.findByRole("checkbox", { name: "Easy-read text" });
  const study = await waitFor(() => {
    const found = document.querySelector<HTMLElement>("[data-study-scope='research_use']");
    expect(found).not.toBeNull();
    return found!;
  });
  return { core, study, chosen };
}

describe("PRV-06", () => {
  test("test_prv06_study_screen_guardian_agreement", async () => {
    const { core, study, chosen } = await family();
    expect(study.dataset.studyState).toBe("off");
    expect(study.textContent).toContain("Help a study of whether the tutor helps students learn.");
    fireEvent.click(within(study).getByRole("button", { name: "Turn on…" }));
    const dialog = await screen.findByRole("dialog", { name: "A learning study" });
    const turnOn = within(dialog).getByRole("button", { name: "Turn on" }) as HTMLButtonElement;
    // "Turn on" stays disabled until an agreement is ticked.
    expect(turnOn.disabled).toBe(true);
    // The profile's band is a minor's (read with its own token, D93): only the parent or guardian's agreement shows.
    expect(within(dialog).queryByRole("checkbox", { name: "I'm the student, I'm 18 or over, and I agree to this study." })).toBeNull();
    expect(within(dialog).getAllByRole("checkbox")).toHaveLength(1);
    expect(core.log.some((r) => r.method === "GET" && r.path === `/v1/profiles/${BEN.profile_id}`)).toBe(true);
    // The parent or guardian ticks the agreement; the student's Turn on is their assent (D87).
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "I'm this student's parent or guardian and I agree to this study." }));
    fireEvent.click(turnOn);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(core.consentSwitches.at(-1)).toEqual({ scope: "research_use", action: "on", guardian_agreed: true });
    await waitFor(() => expect(study.dataset.studyState).toBe("on"));
    expect(core.consents.get(BEN.profile_id)!.find((c) => c.scope === "research_use")).toMatchObject({ granted_by_role: "guardian", method: "in_app_guardian" });
    // Pause, then switch it back on with no guardian step.
    fireEvent.click(within(study).getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(study.dataset.studyState).toBe("paused"));
    fireEvent.click(within(study).getByRole("button", { name: "Turn back on" }));
    await waitFor(() => expect(study.dataset.studyState).toBe("on"));
    expect(core.consentSwitches.slice(-2)).toEqual([{ scope: "research_use", action: "pause" }, { scope: "research_use", action: "on" }]);

    // With the study on, the research export takes the study host's approvals and the student's assent.
    const form = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-research-export]");
      expect(found).not.toBeNull();
      return found!;
    });
    const save = within(form).getByRole("button", { name: "Save the study file" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(form).getByLabelText("School approval reference"), { target: { value: "SCH-2026-014" } });
    fireEvent.change(within(form).getByLabelText("Study protocol reference"), { target: { value: "PROT-7" } });
    expect(save.disabled).toBe(true); // not without the student's own assent
    fireEvent.click(within(form).getByRole("checkbox", { name: "I'm the student and I agree to my learning records going to this study." }));
    fireEvent.click(save);
    await within(form).findByText("The study file is saved.");
    expect(chosen).toEqual(["folder"]);
    expect(core.exports).toEqual([{
      kind: "research_export", profile_ids: [BEN.profile_id], destination: { kind: "file", path: "/synthetic/study-folder" },
      research_approval: { student_assent: true, school_approval_ref: "SCH-2026-014", protocol_ref: "PROT-7" },
    }]);
  });

  test("a student of 18 or over agrees for themselves, and can withdraw", async () => {
    const { core, study } = await family(true);
    fireEvent.click(within(study).getByRole("button", { name: "Turn on…" }));
    const dialog = await screen.findByRole("dialog", { name: "A learning study" });
    // An adult's band: the student agrees for themselves, and no guardian box shows.
    await waitFor(() => expect(within(dialog).queryByRole("checkbox", { name: "I'm this student's parent or guardian and I agree to this study." })).toBeNull());
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "I'm the student, I'm 18 or over, and I agree to this study." }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(study.dataset.studyState).toBe("on"));
    expect(core.consents.get(BEN.profile_id)!.find((c) => c.scope === "research_use")?.granted_by_role).toBe("student_18_plus");
    fireEvent.click(within(study).getByRole("button", { name: "Withdraw" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(study.dataset.studyState).toBe("off"));
    expect(document.querySelector("[data-research-export]")).toBeNull();
  });
});

describe("OBS-20", () => {
  test("test_obs20_report_schema_in_what_leaves_this_device", async () => {
    await family();
    fireEvent.click(screen.getByRole("button", { name: "What a usage report holds" }));
    const schema = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-report-schema]");
      expect(found).not.toBeNull();
      return found!;
    });
    // Every field the published schema lists, with its fixed values; the measurements and what splits them.
    expect([...schema.querySelectorAll<HTMLElement>("[data-report-field]")].map((f) => f.dataset.reportField)).toEqual(["report_id", "app_version", "channel", "os_family", "days"]);
    expect(within(schema.querySelector<HTMLElement>("[data-report-field='channel']")!).getByText("Update channel")).toBeTruthy();
    expect(schema.querySelector("[data-report-field='channel']")!.textContent).toContain("pilot");
    expect(schema.textContent).toContain("2 measurements");
    expect(schema.querySelector("[data-report-metrics]")!.textContent).toBe("ttft_mstool_calls");
    expect(schema.querySelector("[data-report-breakdown='role']")).not.toBeNull();
    expect(schema.textContent).toContain("covering up to 14 days");
  });
});
