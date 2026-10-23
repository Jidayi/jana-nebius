// OBS-15 on the client: Settings → Help → "How the tutor is running" turns each problem component of `GET /v1/health`
// into one plain line with one action, and shows the hardware class and why, the model and content versions and the
// connection. ARC-26 notices that need no engine change: content-only (the runtime cannot run) and a subject whose
// pack failed verification. Against the fake core, with seeded components (the core's side: test_m11e_health.py).
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { ProfileController, StoreHolder, hardwareReport, healthProblems, savingPower } from "@jana/client-core";
import type { Health, ModelCatalogue } from "@jana/contracts-ts";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { LocaleProvider } from "../src/i18n.js";
import { Settings } from "../src/settings/Settings.js";
import { DegradedNotices } from "../src/status/DegradedNotices.js";
import { FAMILY_GROUPS } from "../src/settings/FamilyControls.js";

const BEN = PROFILES[1]!;

afterEach(cleanup);

async function openPanel(core: FakeProfileCore) {
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(BEN.profile_id)).toBe(true);
  render(
    <LocaleProvider locale="en">
      <Settings profiles={profiles} />
    </LocaleProvider>,
  );
  await screen.findByRole("heading", { name: "Help" });
  fireEvent.click(screen.getByRole("button", { name: "How the tutor is running" }));
  await screen.findByText("This computer");
  return profiles;
}

const lines = () => [...document.querySelectorAll("[data-health-line]")].map((li) => [li.getAttribute("data-health-line"), ...[...li.children].map((c) => c.textContent)]);

describe("OBS-15", () => {
  test("obs15_health_panel_conditions", async () => {
    // Healthy (the keychain bridge exists): nothing to act on, and the facts are shown.
    const core = new FakeProfileCore();
    core.health = { status: "ok", readiness: "ready", components: { core: "ok", runtime: "ok", runtime_fallback: "ok", sandbox: "ok", keychain: "ok", speed: "ok", worker: "ok" } };
    core.packs.push({ pack_id: "pack.phy.o", subject: "physics", level: "O", version: "1.2.0", signature_ok: true, size_bytes: 1000 });
    core.features.cloud_tier = true;
    await openPanel(core);
    expect(lines()).toEqual([]);
    expect(screen.getByText("Everything is working as it should.")).toBeTruthy();
    expect(screen.getByText("Standard laptop")).toBeTruthy();
    expect(screen.getByText("Judged from its memory and processor. No speed test has run yet.")).toBeTruthy();
    expect(screen.getByText("synthetic-large, from model pack 0.1.0, in use")).toBeTruthy();
    expect(screen.getByText("Physics, O Level, version 1.2.0")).toBeTruthy();
    expect(screen.getByText("Offline")).toBeTruthy();
    expect(screen.getByText("On: Cloud tutor")).toBeTruthy();
    cleanup();

    // Each seeded condition: its own line and its one action, in the panel's order.
    const seeded = new FakeProfileCore();
    seeded.health = {
      status: "ok", readiness: "ready",
      components: { core: "ok", runtime: "ok", runtime_fallback: "degraded", sandbox: "degraded", keychain: "degraded", speed: "degraded", storage: "degraded", capture: "down", worker: "ok" },
    };
    seeded.packs.push({ pack_id: "pack.chm.o", subject: "chemistry", level: "O", version: "1.0.0", signature_ok: false, size_bytes: 1000 });
    await openPanel(seeded);
    expect(lines()).toEqual([
      ["runtime_fallback", "The tutor moved to a smaller model because the usual one kept stopping.", "Close the app and open it again to go back to the usual model."],
      ["speed", "Answers are taking longer than they should on this computer.", "Plug the computer in and turn off battery saving, or choose a smaller model in Settings, under Tutor models."],
      ["sandbox", "Number checks are running without their usual protection on this computer.", "Install the latest version of the app."],
      ["storage", "This computer is nearly out of space. Progress is still saved, but photos are turned off.", "Free up some disk space on this computer."],
      ["keychain", "Saved keys are protected only by this computer's account login.", "Make sure this computer's account has a password."],
      ["pack_unverified", "Chemistry content couldn't be verified, so it's turned off. Other subjects still work.", "Reinstall it from Settings, under Content."],
    ]);
    expect(screen.queryByText("Everything is working as it should.")).toBeNull();
    // Informational, in Help, not a family control group (D53).
    const panel = screen.getByText("Answers are taking longer than they should on this computer.");
    expect(panel.closest("[data-family-group]")).toBeNull();
    expect(panel.closest("[data-settings-section]")?.getAttribute("data-settings-section")).toBe("help");
    expect(document.querySelectorAll("[data-family-group]")).toHaveLength(2);
  });

  test("the panel names the runtime and content-only states once each, and why a class was chosen", () => {
    const health = (components: Record<string, string>, readiness: Health["readiness"] = "degraded"): Health => ({ status: "degraded", readiness, components: components as Health["components"] });
    const models = (reason_key: string) => ({ installed: [], available: [], assignment: { fast: null, strong: null }, recommended: { fast: null, strong: null, reason_key } });
    // The runtime gave up: the tutor cannot run (MDL-19); a worker down is its own line.
    expect(healthProblems({ health: health({ runtime: "down", worker: "down" }), models: models("hardware_class.low.predicted") })).toEqual(["runtime_down", "worker"]);
    // Still loading is not a problem.
    expect(healthProblems({ health: health({ runtime: "starting" }, "model_loading"), models: null })).toEqual([]);
    // Below the minimum laptop: the content-only line, which already says the tutor cannot run offline (PLT-29).
    expect(healthProblems({ health: health({ runtime: "down" }, "core_ready"), models: models("hardware_class.content_only.below_minimum_ram") })).toEqual(["content_only"]);
  });

  test("the panel shows which check put the computer below the minimum, and survives a failed read", async () => {
    const core = new FakeProfileCore();
    core.health = { status: "ok", readiness: "core_ready", components: { core: "ok", runtime: "down" } };
    core.models = { installed: [], available: [], assignment: { fast: null, strong: null }, recommended: { fast: null, strong: null, reason_key: "hardware_class.content_only.below_minimum_ram" } };
    await openPanel(core);
    expect(lines().map((l) => l[0])).toEqual(["content_only"]);
    expect(screen.getByText("Below what the tutor needs offline")).toBeTruthy();
    expect(screen.getByText("It has less memory than the tutor needs.")).toBeTruthy();
    expect(screen.getByText("No tutor model is running.")).toBeTruthy();
    cleanup();

    const broken = new FakeProfileCore();
    const fetch = broken.fetch;
    broken.fetch = async (input, init) => (/\/v1\/(health|models)$/.test(new URL(String(input)).pathname) ? new Response("{}", { status: 500 }) : fetch(input, init));
    const profiles = new ProfileController(broken.launch, new StoreHolder(), { fetch: broken.fetch });
    await profiles.load();
    await profiles.unlock(BEN.profile_id);
    render(
      <LocaleProvider locale="en">
        <Settings profiles={profiles} />
      </LocaleProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "How the tutor is running" }));
    await screen.findByText("This information couldn't be read just now. Learning still works.");
  });

  test("the family sections are unchanged with the Help section present (D53)", async () => {
    const core = new FakeProfileCore();
    await openPanel(core);
    await screen.findByRole("checkbox", { name: "Downloads" });
    expect(screen.queryByLabelText("Adult PIN")).toBeNull();
    const groups = [...document.querySelectorAll("[data-family-group]")].map((g) => g.getAttribute("data-family-group"));
    expect(groups).toEqual([...FAMILY_GROUPS]);
    expect([...document.querySelectorAll("[data-family-group]")].map((g) => g.closest("[data-settings-section]")?.querySelector("h2")?.textContent)).toEqual(["Online features", "Profiles"]);
  });
});

describe("ARC-26", () => {
  test("content-only and an unverified subject each show their notice above the tutor", async () => {
    const view = (health: Health | null, packs: Parameters<typeof DegradedNotices>[0]["packs"], subject = "physics") =>
      render(
        <LocaleProvider locale="en">
          <DegradedNotices health={health} packs={packs} subject={subject} />
        </LocaleProvider>,
      );
    const down: Health = { status: "degraded", readiness: "degraded", components: { core: "ok", runtime: "down" } };
    view(down, []);
    expect(screen.getByRole("alert").textContent).toBe("The tutor can't run on this computer right now. Lessons and practice still work.");
    cleanup();

    // Restarting is not content-only: no notice while the shell brings the runtime back.
    view({ status: "ok", readiness: "model_loading", components: { core: "ok", runtime: "starting" } }, []);
    expect(document.body.textContent).toBe("");
    cleanup();

    // A pack that failed verification: a notice for its own subject only; other subjects still work.
    const packs = [
      { pack_id: "pack.chm.o", subject: "chemistry", level: "O" as const, version: "1.0.0", signature_ok: false, size_bytes: 1 },
      { pack_id: "pack.phy.o", subject: "physics", level: "O" as const, version: "1.0.0", signature_ok: true, size_bytes: 1 },
    ];
    view({ status: "ok", readiness: "ready", components: { core: "ok", runtime: "ok" } }, packs, "chemistry");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Chemistry content couldn't be verified, so it's turned off for now. Reinstall it from Settings, under Content. Other subjects still work."));
    cleanup();
    view({ status: "ok", readiness: "ready", components: { core: "ok", runtime: "ok" } }, packs, "physics");
    expect(document.body.textContent).toBe("");
  });
});

// M11: the hardware report the core sends once the contract carries `ModelCatalogue.hardware` (contract-additions-m11.json).
const BELOW_MINIMUM = {
  hardware_class: "content_only", basis: "below_minimum_ram", provisional: true, benchmark: null, benchmark_due: false, class_choice: null,
  shortfalls: [{ check: "ram", have: 4, need: 8.0, unit: "GB" }], tutor_path: "none", runtime: null,
};
const contentOnly = (hardware: Record<string, unknown>) =>
  ({ installed: [], available: [], assignment: { fast: null, strong: null },
     recommended: { fast: null, strong: null, reason_key: "hardware_class.content_only.below_minimum_ram" }, hardware }) as unknown as ModelCatalogue;
const atCoreReady: Health = { status: "ok", readiness: "core_ready", components: { core: "ok", runtime: "down" } };

describe("PLT-29", () => {
  test("plt29_below_minimum_notice", async () => {
    // Above the tutor: the unsupported-offline notice names the figure that is short, in place of "cannot run".
    render(
      <LocaleProvider locale="en">
        <DegradedNotices health={atCoreReady} packs={[]} subject="physics" models={contentOnly(BELOW_MINIMUM)} />
      </LocaleProvider>,
    );
    const notice = screen.getByRole("status").textContent ?? "";
    expect(notice).toContain("This computer has 4 GB of memory; the tutor needs 8 GB.");
    expect(notice).toContain("Lessons, practice and worked solutions work here.");
    expect(screen.queryByRole("alert")).toBeNull();
    cleanup();
    // With a school server or the online tier the tutor runs there: no notice that it cannot.
    render(
      <LocaleProvider locale="en">
        <DegradedNotices health={atCoreReady} packs={[]} subject="physics" models={contentOnly({ ...BELOW_MINIMUM, tutor_path: "online" })} />
      </LocaleProvider>,
    );
    expect(document.body.textContent).toBe("");
    cleanup();
    // In the health panel (Settings, open to every profile): the class, the check that failed and its figures.
    const core = new FakeProfileCore();
    core.health = atCoreReady;
    core.models = contentOnly(BELOW_MINIMUM);
    await openPanel(core);
    expect(lines().map((l) => l[0])).toEqual(["content_only"]);
    expect(document.querySelector("[data-shortfall=ram]")?.textContent).toBe("This computer has 4 GB of memory; the tutor needs 8 GB.");
  });

  test("each kind of shortfall is named with its figures", () => {
    const report = hardwareReport(contentOnly({ ...BELOW_MINIMUM, shortfalls: [
      { check: "disk", have: 4.2, need: 10, unit: "GB" }, { check: "cpu", have: 2016, need: 2018, unit: "year" },
      { check: "cpu", have: "x86", need: "64-bit", unit: "" }, { check: "nonsense", have: 1, need: 2, unit: "" },
    ] }));
    expect(report?.shortfalls.map((s) => s.check)).toEqual(["disk", "cpu", "cpu"]);
    render(
      <LocaleProvider locale="en">
        <DegradedNotices health={atCoreReady} packs={[]} subject="physics" models={contentOnly({ ...BELOW_MINIMUM, shortfalls: report?.shortfalls })} />
      </LocaleProvider>,
    );
    const notice = screen.getByRole("status").textContent ?? "";
    expect(notice).toContain("This computer has 4.2 GB of free disk space; the tutor needs 10 GB.");
    expect(notice).toContain("This computer's processor is from 2016; the tutor needs one from 2018 or later.");
    expect(notice).toContain("This computer's processor can't run the tutor (x86); it needs 64-bit.");
    // A core without the report: nothing is invented.
    expect(hardwareReport({ installed: [], available: [], assignment: { fast: null, strong: null }, recommended: { fast: null, strong: null, reason_key: "x" } })).toBeNull();
  });
});

describe("PLT-04", () => {
  test("the panel shows the runtime build in use and why the first choice was set aside", async () => {
    const core = new FakeProfileCore();
    core.health = { status: "ok", readiness: "ready", components: { core: "ok", runtime: "ok", runtime_variant: "degraded", keychain: "ok" } };
    core.models = { ...core.models, hardware: { ...BELOW_MINIMUM, hardware_class: "mid", basis: "measured", shortfalls: [], tutor_path: "local",
      runtime: { variant: "cpu-avx2", fallbacks: [{ variant: "vulkan", reason: "crashed (segmentation fault) during its first generation" }] } } } as unknown as ModelCatalogue;
    await openPanel(core);
    expect(lines()).toEqual([["runtime_variant", "The tutor is running in a slower way on this computer, because the faster way stopped working.",
      "Update this computer's graphics driver, then close the app and open it again."]]);
    expect(screen.getByText("Using the cpu-avx2 build of the model runtime.")).toBeTruthy();
    expect(document.querySelector("[data-runtime-fallback=vulkan]")?.textContent).toBe("The vulkan build was set aside: crashed (segmentation fault) during its first generation.");
  });
});

describe("PLT-22", () => {
  test("the low-battery banner shows while the app saves battery", () => {
    render(
      <LocaleProvider locale="en">
        <DegradedNotices health={{ status: "ok", readiness: "ready", components: { core: "ok", runtime: "ok", power: "degraded" } }} packs={[]} subject="physics" />
      </LocaleProvider>,
    );
    expect(screen.getByRole("status").textContent).toBe("Saving battery: shorter answers");
    expect(savingPower({ status: "ok", readiness: "ready", components: { power: "ok" } })).toBe(false);
  });
});

describe("PLT-09", () => {
  test("the panel suggests a lower setting when steps often run over", () => {
    const health: Health = { status: "ok", readiness: "ready", components: { core: "ok", runtime: "ok", speed: "ok", class_lower: "degraded" } };
    expect(healthProblems({ health, models: null })).toEqual(["class_lower"]);
  });
});


test("unavailable tutor actions open lessons and online settings", () => {
  const open = vi.fn(); const online = vi.fn();
  render(<LocaleProvider locale="en"><DegradedNotices health={{ status: "degraded", readiness: "degraded", components: { runtime: "down" } }} packs={[]} subject="physics" onOpenLessons={open} onOnlineFeatures={online} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Open lessons" }));
  expect(open).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "Online features" })).toBeNull();
  cleanup();
  const models = { hardware: BELOW_MINIMUM } as unknown as ModelCatalogue;
  render(<LocaleProvider locale="en"><DegradedNotices health={null} models={models} packs={[]} subject="physics" onOpenLessons={open} onOnlineFeatures={online} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Open lessons" }));
  fireEvent.click(screen.getByRole("button", { name: "Online features" }));
  expect(open).toHaveBeenCalledTimes(2); expect(online).toHaveBeenCalledTimes(1);
});
