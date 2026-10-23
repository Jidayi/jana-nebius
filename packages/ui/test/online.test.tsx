// UXS-07, ARC-11 and D70 on the client: Settings → Online features (adult PIN) has one row per feature the core lists,
// each off on a fresh install with its TABLE UXS-07a copy; a consent-gated row turns on only through the confirmation
// that shows the consent line and the guardian attestation, and turning it off withdraws. The cloud tutor row is the
// subscription (D70), not a switch. Against the fake core.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { BASE } from "@jana/i18n";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { LocaleProvider } from "../src/i18n.js";
import { Settings } from "../src/settings/Settings.js";

const [ADA, BEN, CHI] = PROFILES as [(typeof PROFILES)[number], (typeof PROFILES)[number], (typeof PROFILES)[number]];

afterEach(() => cleanup());

async function adultControls(setup: (core: FakeProfileCore) => void = () => undefined) {
  const core = new FakeProfileCore();
  setup(core);
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(BEN.profile_id)).toBe(true);
  render(
    <LocaleProvider locale="en">
      <Settings profiles={profiles} />
    </LocaleProvider>,
  );
  await screen.findByRole("checkbox", { name: "Easy-read text" });
  await screen.findByRole("checkbox", { name: "Downloads" });
  return { core, profiles };
}

const rows = () => [...document.querySelectorAll<HTMLElement>("[data-online-feature]")];
const row = (feature: string) => document.querySelector<HTMLElement>(`[data-online-feature='${feature}']`)!;
const dialog = () => screen.queryByRole("alertdialog");
const patches = (core: FakeProfileCore) => core.log.filter((r) => r.method === "PATCH" && r.path === "/v1/connectivity");

/** TABLE UXS-07a, the S2 rows: what leaves this computer and what happens offline. */
const UXS07A: Record<string, [string, string, string]> = {
  cloud_tier: ["Cloud tutor", "The question, the working so far and the topic. Not your name, not your photos unless you attach one.", "Uses the tutor on this computer."],
  downloads: ["Downloads", "Which app and pack versions you have and the files you ask for. No learning data.", "Install packs and models from a USB stick instead."],
  update_checks: ["Update checks", "Your app version, update channel and type of computer. No learning data.", "Install updates from a USB stick instead."],
  telemetry: ["Usage reports", "Counts and timings only. No questions, answers or photos.", "Saved here and sent next time you're online."],
  crash_reports: ["Crash reports", "A crash report with personal details removed, after you look at it.", "Kept on this computer."],
};

describe("UXS-07", () => {
  test("uxs07_all_off_by_default", async () => {
    const { core } = await adultControls();
    await waitFor(() => expect(row("cloud_tier").textContent).toContain("Needs a subscription"));
    // Exactly the features the core lists for this stage, in the order of TABLE ARC-07a, inside the adult controls.
    expect(rows().map((r) => r.getAttribute("data-online-feature"))).toEqual(Object.keys(core.features));
    expect(rows().map((r) => r.getAttribute("data-online-feature"))).toEqual(["cloud_tier", "downloads", "update_checks", "telemetry", "crash_reports"]);
    for (const r of rows()) expect(r.closest("[data-family-group='online']")).not.toBeNull();
    for (const [feature, [name, leaves, offline]] of Object.entries(UXS07A)) {
      const text = row(feature).textContent ?? "";
      expect(text, feature).toContain(name);
      expect(text, feature).toContain(leaves);
      expect(text, feature).toContain(offline);
      // The copy comes from the catalogue keys of the row.
      expect(BASE[`settings.online.feature.${feature}`]).toBe(name);
      expect(BASE[`settings.online.leaves.${feature}`]).toBe(leaves);
      expect(BASE[`settings.online.offline.${feature}`]).toBe(offline);
    }
    // Every switch is off; the cloud tutor is off because nobody has subscribed (D70).
    for (const feature of ["downloads", "update_checks", "telemetry", "crash_reports"]) {
      const box = within(row(feature)).getByRole("checkbox") as HTMLInputElement;
      expect(box.checked, feature).toBe(false);
    }
    expect(within(row("cloud_tier")).queryByRole("checkbox")).toBeNull();
    expect(row("cloud_tier").textContent).toContain("Off");
    expect(screen.getByRole("button", { name: "Turn off all online features" })).toBeTruthy();
    // A fresh install sent no switch at all.
    expect(patches(core)).toEqual([]);
  });

  test("uxs07_consent_gate", async () => {
    const { core } = await adultControls((c) => {
      c.subscription = {
        state: "pending_consent", subscription_id: "sub_test_1", period_end: "2026-12-31T00:00:00.000Z", allowance_used_up: false,
        profiles: [{ profile_id: ADA.profile_id, consent: "needed" }, { profile_id: CHI.profile_id, consent: "recorded" }],
      };
    });

    // A data-sending feature: the switch opens the confirmation; nothing is sent until "Turn on".
    fireEvent.click(within(row("telemetry")).getByRole("checkbox"));
    let confirm = dialog()!;
    expect(confirm.textContent).toContain("Turn on usage reports?");
    expect(confirm.textContent).toContain(UXS07A.telemetry![1]);
    expect(confirm.textContent).toContain("Send anonymous counts that help us make the app faster. No questions, answers or names.");
    expect(confirm.textContent).toContain("I am this student's parent or guardian.");
    expect(patches(core)).toEqual([]);
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(dialog()).toBeNull();
    expect(patches(core)).toEqual([]);
    expect((within(row("telemetry")).getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
    expect(core.deviceConsents.get("telemetry")).toBeUndefined();

    // "Turn on" records the consent and the switch in one action, with the adult token.
    fireEvent.click(within(row("telemetry")).getByRole("checkbox"));
    fireEvent.click(within(dialog()!).getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect((within(row("telemetry")).getByRole("checkbox") as HTMLInputElement).checked).toBe(true));
    expect(patches(core)).toHaveLength(1);
    expect(patches(core)[0]!.body).toEqual({ features: { telemetry: true } });
    expect(patches(core)[0]!.headers["x-adult-token"]).toBeUndefined();
    expect(core.deviceConsents.get("telemetry")).toBe(true);

    // Turning it off withdraws the consent at once.
    fireEvent.click(within(row("telemetry")).getByRole("checkbox"));
    await waitFor(() => expect((within(row("telemetry")).getByRole("checkbox") as HTMLInputElement).checked).toBe(false));
    expect(dialog()).toBeNull();
    expect(patches(core).at(-1)!.body).toEqual({ features: { telemetry: false } });
    expect(core.deviceConsents.get("telemetry")).toBe(false);

    // Downloads need only the switch: the confirmation names the data, with no consent text or attestation.
    fireEvent.click(within(row("downloads")).getByRole("checkbox"));
    confirm = dialog()!;
    expect(confirm.textContent).toContain(UXS07A.downloads![1]);
    expect(confirm.textContent).not.toContain("parent or guardian");
    fireEvent.click(within(confirm).getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(core.features.downloads).toBe(true));
    expect(core.deviceConsents.get("downloads")).toBeUndefined();

    // The cloud tutor (D70): subscribing turned it on, waiting for the guardian's consent for Ada.
    await waitFor(() => expect(row("cloud_tier").textContent).toContain("Waiting for a parent or guardian's consent for Ada."));
    fireEvent.click(within(row("cloud_tier")).getByRole("button", { name: "Give consent" }));
    confirm = dialog()!;
    expect(confirm.textContent).toContain("Turn on the cloud tutor? The question, the working so far and the topic will be sent to the cloud tutor when you're online. Your name is not sent.");
    expect(confirm.textContent).toContain(BASE["settings.online.consent.cloud_tier"]!);
    expect(confirm.textContent).toContain("I am this student's parent or guardian.");
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(core.log.some((r) => r.method === "POST" && r.path === "/v1/subscription")).toBe(false);
    fireEvent.click(within(row("cloud_tier")).getByRole("button", { name: "Give consent" }));
    fireEvent.click(within(dialog()!).getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(row("cloud_tier").textContent).toContain("On, through the subscription."));
    const apply = core.log.find((r) => r.method === "POST" && r.path === "/v1/subscription")!;
    expect(apply.headers["x-adult-token"]).toBeUndefined();
    expect((apply.body as { consents: unknown[] }).consents).toEqual([{ profile_id: ADA.profile_id, notice_version: "2026-10.d1" }]);
    expect(core.consents.get(ADA.profile_id)!.find((c) => c.scope === "cloud_tier")?.granted).toBe(true);
    expect(core.features.cloud_tier).toBe(true);

    // Ending the subscription turns the cloud tutor off and withdraws its consents, after a confirmation.
    fireEvent.click(within(row("cloud_tier")).getByRole("button", { name: "Turn off the cloud tutor" }));
    expect(dialog()!.textContent).toContain("This ends the subscription");
    fireEvent.click(within(dialog()!).getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(row("cloud_tier").textContent).toContain("Needs a subscription"));
    expect(core.log.some((r) => r.method === "DELETE" && r.path === "/v1/subscription")).toBe(true);
    expect(core.features.cloud_tier).toBe(false);
    expect(core.consents.get(ADA.profile_id)!.find((c) => c.scope === "cloud_tier")?.granted).toBe(false);
  });
});

// BIZ-18 (D121): one monthly allowance per student on every plan, no model picker and no second (premium) quota.
describe("BIZ-18", () => {
  test("biz18_one_allowance_no_picker", async () => {
    await adultControls((c) => {
      c.subscription = {
        state: "active", subscription_id: "sub_test_1", period_end: "2026-12-31T00:00:00.000Z", allowance_used_up: true,
        profiles: [{ profile_id: ADA.profile_id, consent: "recorded" }],
      };
    });
    await waitFor(() => expect(row("cloud_tier").textContent).toContain("On, through the subscription."));
    // The one allowance, monthly (D33), with the on-device tutor after it: no upgrade, no second quota to buy.
    expect(row("cloud_tier").textContent).toContain("This month's allowance is used up. The tutor on this computer answers until it renews.");
    const online = row("cloud_tier").closest<HTMLElement>("[data-family-group='online']")!;
    for (const role of ["combobox", "listbox", "radiogroup", "radio", "slider", "spinbutton"]) {
      expect(within(online).queryAllByRole(role), role).toEqual([]);
    }
    expect(row("cloud_tier").textContent ?? "").not.toMatch(/\bmodel|premium|quota|upgrade|price|NGN|US\$/i);
    // No copy anywhere offers a plan's model, a premium plan or a second quota; the subscription's copy names no model.
    for (const [key, text] of Object.entries(BASE)) {
      expect(text, key).not.toMatch(/premium (plan|quota|model|tier|tutor)|\bquota\b|(choose|pick|select|switch)[^.]{0,30}(cloud|online|premium) (tutor )?model/i);
      if (key.startsWith("settings.online.cloud") || key.endsWith(".cloud_tier") || key.startsWith("licence.cloud.")) expect(text, key).not.toMatch(/\bmodel/i);
    }
  });
});
