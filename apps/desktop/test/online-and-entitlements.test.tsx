// PLT-18 and BIZ-06 in the app as it is wired. Settings → Online features lists every feature of TABLE ARC-07a the
// core reports, each with what leaves this computer, its offline equivalent and its switch (the cloud tutor's switch is
// the subscription, D70), all off on a fresh install. No student-facing screen has a payment form: every gallery state
// renders without one, the catalogue has no payment-form copy, and the shipped client code takes no card details and
// loads no payment provider. Against the fake core, with the gallery's fixtures.
import fs from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { ONLINE_FEATURES } from "@jana/client-core";
import { errors } from "@jana/contracts-ts";
import { BASE } from "@jana/i18n";
import { RENDERERS } from "@jana/renderers";
import { defaultRegistry } from "@jana/ui";
import { GalleryView, STATES } from "@jana/ui/gallery";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { registerVisuals } from "../src/visuals.js";
import { findMenuItem } from "./student-menu.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");

afterEach(() => cleanup());

/** TABLE ARC-07a's features, in its order. */
const ARC07A = ["cloud_tier", "downloads", "update_checks", "cloud_backup", "multi_device", "parent_remote_view", "cloud_voice", "study_materials", "telemetry", "crash_reports"];

const rows = () => [...document.querySelectorAll<HTMLElement>("[data-online-feature]")];

async function onlineFeatures(fake: FakeProfileCore) {
  render(<App runtime={createRuntime(fake.launch, fake.fetch)} />);
  fireEvent.click(await screen.findByRole("button", { name: /^Ada/ }));
  fireEvent.click(await findMenuItem("Settings"));
  await waitFor(() => expect(rows().length).toBeGreaterThan(0));
}

describe("PLT-18", () => {
  test("plt18_online_features_page_complete", async () => {
    // The client knows exactly the features of TABLE ARC-07a, each a feature of the contract.
    expect([...ONLINE_FEATURES]).toEqual(ARC07A);
    for (const feature of ARC07A) expect(errors("api/events#/$defs/online_feature", feature), feature).toEqual([]);

    // A fresh install whose core lists every feature (here all of them, past the stage that ships each): one row per
    // feature, in the table's order, each with its name, what leaves this computer, the offline equivalent and its
    // switch, every one off. Nothing was switched by opening the page.
    const fake = new FakeProfileCore();
    for (const feature of ARC07A) fake.features[feature] = false;
    await onlineFeatures(fake);
    await waitFor(() => expect(rows().map((r) => r.getAttribute("data-online-feature"))).toEqual(ARC07A));
    for (const feature of ARC07A) {
      const row = document.querySelector<HTMLElement>(`[data-online-feature='${feature}']`)!;
      const text = row.textContent ?? "";
      for (const key of ["feature", "leaves", "offline"]) {
        const copy = BASE[`settings.online.${key}.${feature}`];
        expect(copy, `${key} ${feature}`).toBeTruthy();
        expect(text, `${key} ${feature}`).toContain(copy);
      }
      if (feature === "cloud_tier") {
        // Subscribing is the cloud tutor's switch (D70); it is off until someone subscribes.
        await waitFor(() => expect(row.textContent).toContain(BASE["settings.online.cloud.off"]!));
        expect(within(row).queryByRole("checkbox")).toBeNull();
      } else {
        const box = within(row).getByRole("checkbox", { name: BASE[`settings.online.feature.${feature}`]! }) as HTMLInputElement;
        expect(box.checked, feature).toBe(false);
      }
    }
    expect(fake.log.filter((r) => r.method === "PATCH" && r.path === "/v1/connectivity")).toEqual([]);
    expect(Object.values(fake.features).some(Boolean)).toBe(false);
  });
});

const PAYMENT_COPY = /card number|cvv|cvc|security code|expiry date|expiration|billing address|pay now|enter your card|payment details|card details/i;
const PAYMENT_FIELD = "input[autocomplete^='cc-'], input[name*='card' i], input[name*='cvv' i], input[name*='cvc' i], input[name*='iban' i], input[type='tel'][inputmode='numeric']";

function shipped(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" || entry.name === "generated" ? [] : shipped(full);
    return /\.(tsx?|jsx?|html)$/.test(entry.name) ? [full] : [];
  });
}

describe("BIZ-06", () => {
  test("biz06_no_payment_ui_for_students", async () => {
    // Every state of every student-facing screen in the gallery renders without a payment form.
    const registry = registerVisuals(defaultRegistry(), RENDERERS);
    const quiet = (["error", "warn", "log", "info"] as const).map((level) => vi.spyOn(console, level).mockImplementation(() => undefined));
    try {
      for (const state of STATES) {
        const { container, unmount } = render(<GalleryView state={state} registry={registry} />);
        expect(container.querySelector(PAYMENT_FIELD), state.id).toBeNull();
        expect(container.textContent ?? "", state.id).not.toMatch(PAYMENT_COPY);
        unmount();
      }
    } finally {
      quiet.forEach((spy) => spy.mockRestore());
    }

    // Settings, where the cloud tutor's subscription shows, says what it is and who unlocks it: no form to pay.
    const fake = new FakeProfileCore();
    await onlineFeatures(fake);
    expect(document.querySelector(PAYMENT_FIELD)).toBeNull();
    expect(document.body.textContent).not.toMatch(PAYMENT_COPY);

    // The catalogue has no payment-form copy, and the shipped client code takes no card details and loads no payment
    // provider's script.
    for (const [key, copy] of Object.entries(BASE)) expect(copy, key).not.toMatch(PAYMENT_COPY);
    const sources = ["apps/desktop/src", "packages/ui/src", "packages/client-core/src"].flatMap((dir) => shipped(path.join(ROOT, dir)));
    expect(sources.length).toBeGreaterThan(20);
    for (const file of sources) {
      const code = fs.readFileSync(file, "utf8");
      expect(code, file).not.toMatch(/autoComplete=["']cc-|stripe|paystack|flutterwave|paypal|braintree|checkout\.js/i);
    }
  });
});
