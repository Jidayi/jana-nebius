// UIA-23, UXS-06, UXS-08, DSN-19, PRD-21 and PRV-28 on the client: the connectivity indicator at the bottom of the left
// rail, its popover, the egress line of a turn, the pre-send notices of the gallery, and that no switch for an online
// feature is reachable without the adult PIN. Against the fake core, which refuses what the real one refuses.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  INDICATOR_ALIAS, INDICATOR_STATES, ONLINE_FEATURES, ProfileController, StoreHolder, emptyStore, hydrate, reduce, type Envelope, type IndicatorState,
} from "@jana/client-core";
import { BASE } from "@jana/i18n";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { GalleryView, STATES } from "../gallery/index.js";
import { AppFrame } from "../src/connectivity/AppFrame.js";
import { PRE_SEND_PATHS } from "../src/connectivity/EgressNotice.js";
import { TOKENS } from "../src/generated/tokens.js";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { Settings } from "../src/settings/Settings.js";
import { StoreProvider } from "../src/store.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { TutorScreen } from "../src/TutorScreen.js";
import { snapshot, SESSION, EPOCH } from "./harness.js";

const [ADA, BEN] = PROFILES as [(typeof PROFILES)[number], (typeof PROFILES)[number]];

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

let seq = 0;
let ids = 0;
const id = (prefix: string) => `${prefix}_${(++ids).toString(32).toUpperCase().padStart(26, "0")}`;

async function runtime(setup: (core: FakeProfileCore) => void = () => undefined, profileId = ADA.profile_id) {
  const core = new FakeProfileCore();
  setup(core);
  const holder = new StoreHolder();
  const profiles = new ProfileController(core.launch, holder, { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(profileId)).toBe(true);
  holder.update(() => hydrate(emptyStore(), snapshot()));
  seq = 0;
  return { core, holder, profiles };
}

/** As the session controller commits a batch: the store folds it, then the app slice sees it. */
function feed(holder: StoreHolder, event: Record<string, unknown> & { type: string }, turnId: string | null): Envelope {
  seq += 1;
  const envelope: Envelope = { v: 1, channel: "session", seq, epoch: EPOCH, session_id: SESSION, turn_id: turnId, ts: Date.now(), event };
  act(() => {
    holder.update((s) => reduce(s, envelope));
    holder.deliver([envelope]);
  });
  return envelope;
}

function appEvent(profiles: ProfileController, event: Record<string, unknown> & { type: string }): void {
  seq += 1;
  act(() => profiles.connectivity.receive({ v: 1, channel: "app", seq, epoch: "ep_app", session_id: null, turn_id: null, ts: Date.now(), event }));
}

const egress = (feature: string, state: "started" | "ended" | "blocked", destination: string) =>
  ({ type: "egress.notice", feature, state, destination_label: destination, data_classes: feature === "cloud_tier" ? ["question_text", "board"] : ["diagnostics"] });

function frame(profiles: ProfileController, holder: StoreHolder, child: ReactNode = null) {
  return render(
    <LocaleProvider locale="en">
      <RegistryProvider registry={defaultRegistry()}>
        <StoreProvider holder={holder} session={null}>
          <AppFrame profiles={profiles}>{child}</AppFrame>
        </StoreProvider>
      </RegistryProvider>
    </LocaleProvider>,
  );
}

const trigger = () => document.querySelector<HTMLButtonElement>("[data-connectivity-indicator]")!;
const label = () => trigger().textContent ?? "";
const popover = () => document.querySelector<HTMLElement>("[data-connectivity-popover]");

async function settled(text: string): Promise<void> {
  await waitFor(() => expect(label()).toBe(text));
}

function startTurn(holder: StoreHolder): string {
  const turnId = id("trn");
  feed(holder, { type: "turn.start", turn_id: turnId, user_message_id: id("msg"), client_message_id: null, intent: "ask", mode: "guided", fork: false }, turnId);
  return turnId;
}

function endTurn(holder: StoreHolder, turnId: string): void {
  feed(holder, { type: "turn.end", status: "complete", stop_reason: "completed", elapsed_ms: 1000, usage: null, verification: "not_applicable", persisted: { message_id: id("msg"), part_ids: [] }, degraded: false, degraded_reason: null }, turnId);
}

function tutorText(holder: StoreHolder, turnId: string, text: string): void {
  const partId = id("prt");
  feed(holder, { type: "part.start", part_id: partId, kind: "text", index: 0 }, turnId);
  feed(holder, { type: "text.delta", part_id: partId, delta: text }, turnId);
  feed(holder, { type: "part.end", part_id: partId, status: "complete", duration_ms: 1 }, turnId);
}

describe("UIA-23", () => {
  test("uia23_egress_indicator", async () => {
    const { holder, profiles } = await runtime((core) => {
      core.features.cloud_tier = true;
      core.network = "online";
    });
    frame(profiles, holder, <TutorScreen sessionId={SESSION} />);
    await settled("Online");
    const turnId = startTurn(holder);
    const started = feed(holder, egress("cloud_tier", "started", "Cloud tutor"), turnId);
    // While the cloud request is in flight the indicator names where the data is going, as the notice labels it.
    expect(label()).toBe((started.event as { destination_label: string }).destination_label);
    expect(trigger().getAttribute("data-state")).toBe("cloud-tutor");
    // The turn says where its data is going, in plain words, while it is sent.
    expect(document.querySelector("[data-turn-egress]")?.textContent).toContain("Sending to Cloud tutor");
    tutorText(holder, turnId, "Momentum is mass times velocity.");
    feed(holder, egress("cloud_tier", "ended", "Cloud tutor"), turnId);
    // On `ended` the indicator returns to its resting state; nothing is shown as leaving any more.
    expect(label()).toBe("Online");
    expect(screen.queryByText(/Sending to/)).toBeNull();
    endTurn(holder, turnId);
    expect(screen.getByText("Answered by the online tutor")).toBeTruthy();

    // A blocked attempt and the network dropping never interrupt the composer, the transcript or the board.
    const next = startTurn(holder);
    feed(holder, egress("cloud_tier", "blocked", "Cloud tutor"), next);
    appEvent(profiles, { type: "connectivity.status", network: "offline", checked_ts: 1, features: [{ feature: "cloud_tier", enabled: true, state: "unavailable", queued_items: 0 }] });
    expect(label()).toBe("Offline");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText("Momentum is mass times velocity.")).toBeTruthy();
    expect(document.querySelector("[contenteditable], textarea")).not.toBeNull();
  });
});

describe("UXS-06", () => {
  test("uxs06_default_no_egress", async () => {
    const outside = vi.spyOn(globalThis, "fetch");
    const { core, holder, profiles } = await runtime();
    frame(profiles, holder, <TutorScreen sessionId={SESSION} />);
    await settled("On this computer");
    expect(trigger().getAttribute("data-alias")).toBe("connectivity-local");
    fireEvent.click(trigger());
    expect(popover()?.textContent).toContain("Everything stays on this computer.");
    expect(within(popover()!).queryByRole("button", { name: "Send now" })).toBeNull();
    fireEvent.click(trigger());

    // A scripted local session: turns answered on this computer change nothing.
    for (let n = 0; n < 3; n += 1) {
      const turnId = startTurn(holder);
      tutorText(holder, turnId, `Local answer ${n}`);
      endTurn(holder, turnId);
      expect(label()).toBe("On this computer");
    }
    expect(screen.queryByText("Answered by the online tutor")).toBeNull();

    // Two hours on: the client polls nothing, and every request it made went to the local core.
    const requests = core.log.length;
    vi.useFakeTimers();
    act(() => vi.advanceTimersByTime(2 * 60 * 60 * 1000));
    vi.useRealTimers();
    expect(core.log.length).toBe(requests);
    expect(outside).not.toHaveBeenCalled();
    expect(core.log.every((r) => r.path.startsWith("/v1/"))).toBe(true);
    expect(core.log.some((r) => r.path === "/v1/connectivity/send-now")).toBe(false);
    expect(label()).toBe("On this computer");
  });

  test("uxs06_egress_always_shown", async () => {
    const { holder, profiles } = await runtime((core) => {
      for (const f of Object.keys(core.features)) core.features[f] = true;
      core.network = "online";
    });
    frame(profiles, holder);
    await settled("Online");
    // Every feature's request, and one of a feature this build does not know, shows while it is in flight.
    for (const feature of [...ONLINE_FEATURES, "a_newer_feature"]) {
      const cloud = feature === "cloud_tier";
      const turnId = cloud ? startTurn(holder) : null;
      if (cloud) feed(holder, egress(feature, "started", "Cloud tutor"), turnId);
      else appEvent(profiles, egress(feature, "started", "Somewhere"));
      expect(label(), feature).toBe(cloud ? "Cloud tutor" : "Sending");
      expect(trigger().getAttribute("data-alias"), feature).toBe(cloud ? "connectivity-online" : "connectivity-egress");
      if (cloud) feed(holder, egress(feature, "ended", "Cloud tutor"), turnId);
      else appEvent(profiles, egress(feature, "ended", "Somewhere"));
      expect(label(), feature).toBe("Online");
    }
    // The popover's first line names what is being sent.
    appEvent(profiles, egress("telemetry", "started", "Usage reports"));
    fireEvent.click(trigger());
    expect(popover()?.textContent).toContain("Sending a usage report: counts and timings only.");
    // A blocked attempt sent nothing: it is never shown as sending.
    appEvent(profiles, egress("telemetry", "ended", "Usage reports"));
    appEvent(profiles, egress("downloads", "blocked", "Downloads"));
    expect(label()).toBe("Online");
    // Two requests at once: the indicator stays on until both have ended.
    appEvent(profiles, egress("downloads", "started", "Downloads"));
    appEvent(profiles, egress("update_checks", "started", "Update check"));
    appEvent(profiles, egress("downloads", "ended", "Downloads"));
    expect(label()).toBe("Sending");
    appEvent(profiles, egress("update_checks", "ended", "Update check"));
    expect(label()).toBe("Online");
  });
});

describe("UXS-08", () => {
  test("uxs08_queue_visible_after_restart", async () => {
    const setup = (core: FakeProfileCore) => {
      core.features.telemetry = true;
      core.features.crash_reports = true;
      core.queued.telemetry = 2;
      core.queued.crash_reports = 1;
      core.network = "offline";
    };
    const first = await runtime(setup);
    frame(first.profiles, first.holder);
    await settled("Offline");
    cleanup();

    // A restart: a new client seeds from the core and shows the same queue.
    const { core, holder, profiles } = await runtime(setup);
    frame(profiles, holder);
    await settled("Offline");
    fireEvent.click(trigger());
    const pop = popover()!;
    expect(pop.textContent).toContain("Working offline. 3 updates will be sent when you're connected.");
    expect(pop.textContent).toContain("Waiting to sync · 3 updates");
    expect(within(pop).getByText("2 waiting")).toBeTruthy();
    expect(within(pop).queryByRole("button", { name: "Send now" })).toBeNull(); // only when online
    expect(screen.queryByRole("alertdialog")).toBeNull();

    // Back online: "Send now" sends the queue once.
    core.network = "online";
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await settled("Online");
    fireEvent.click(await within(popover()!).findByRole("button", { name: "Send now" }));
    await waitFor(() => expect(popover()?.textContent).not.toContain("Waiting to sync"));
    expect(core.log.filter((r) => r.method === "POST" && r.path === "/v1/connectivity/send-now")).toHaveLength(1);
    expect(core.queued.telemetry).toBe(0);
  });
});

/** The colour roles a class names (`text-info`, `bg-connectivity-local`), and nothing for sizes or layout. */
function colourRoles(element: Element): string[] {
  const roles = new Set([...Object.keys(TOKENS.color), ...Object.keys(TOKENS.aliases)]);
  const classes = [element, ...element.querySelectorAll("*")].flatMap((el) => [...el.classList]);
  return classes.map((c) => /^(?:[a-z-]+:)*(?:text|bg|border|fill|stroke|ring|outline)-(.+)$/.exec(c)?.[1] ?? "").filter((r) => roles.has(r));
}

describe("DSN-19", () => {
  test("dsn19_indicator_calm", () => {
    const states = STATES.filter((s) => s.component === "ConnectivityIndicator");
    // Every S2 state of TABLE UXS-06a has a gallery state.
    expect(new Set(states.map((s) => s.context.connectivity))).toEqual(new Set(INDICATOR_STATES));
    for (const state of states) {
      render(<GalleryView state={state} />);
      const item = trigger();
      const expected = INDICATOR_ALIAS[state.context.connectivity as IndicatorState];
      expect(item.getAttribute("data-state"), state.id).toBe(state.context.connectivity);
      expect(item.getAttribute("data-alias"), state.id).toBe(expected);
      // Only connectivity-* aliases, and the one of TABLE DSN-19a for the state.
      const roles = colourRoles(item);
      expect(roles.length, state.id).toBeGreaterThan(0);
      expect(roles.every((r) => r === expected), `${state.id}: ${roles.join(" ")}`).toBe(true);
      // No motion but the label morph: no pulse, flash, transition or press animation.
      const classes = [item, ...item.querySelectorAll("*")].flatMap((el) => [...el.classList]);
      expect(classes.filter((c) => /^jana-/.test(c)), state.id).toEqual(["jana-morph"]);
      expect(classes.filter((c) => /animate-|pulse|transition|duration-|blink/.test(c)), state.id).toEqual([]);
      // Never danger, never the verified green, anywhere the indicator draws (the popover included).
      const all = document.querySelector("[data-gallery-id]")!;
      expect(colourRoles(all).filter((r) => /danger|verified/.test(r)), state.id).toEqual([]);
      cleanup();
    }
    const source = fs.readFileSync(path.join(import.meta.dirname, "../src/connectivity/ConnectivityIndicator.tsx"), "utf8");
    expect(source).not.toMatch(/danger|verified|animate-|jana-press|jana-reveal|jana-shimmer|jana-spinner/);
    // The label morph is a motion primitive, with its reduced-motion rule.
    const motion = fs.readFileSync(path.join(import.meta.dirname, "../src/primitives/motion.css"), "utf8");
    expect(motion).toMatch(/\[data-reduced-motion="true"\][^{]*\.jana-morph/);
  });
});

describe("PRD-21", () => {
  test("prd21_egress_indicator_shown", async () => {
    // Cloud tier on (a subscription, D70): the online indicator, the first-use notice and the cloud turn's notice.
    const on = await runtime((core) => {
      core.features.cloud_tier = true;
      core.subscription = { ...core.subscription, state: "active", subscription_id: "sub_1" };
      core.network = "online";
    });
    frame(on.profiles, on.holder, <TutorScreen sessionId={SESSION} />);
    await settled("Online");
    expect(trigger().getAttribute("data-alias")).toBe("connectivity-online");
    const turnId = startTurn(on.holder);
    const partId = id("prt");
    feed(on.holder, { type: "part.start", part_id: partId, kind: "card", index: 0 }, turnId);
    feed(on.holder, {
      type: "card.open", request_id: id("req"), part_id: partId,
      card: { card_type: "confirm", purpose: "egress", title: "Send this question to the online tutor?", body: "This question will be sent to the online tutor. Your name is not sent.", confirm_label_key: "egress.first_use.ok", cancel_label_key: "egress.first_use.keep_local" },
    }, turnId);
    expect(screen.getByText("This question will be sent to the online tutor. Your name is not sent.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "OK" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Keep it on this computer" })).toBeTruthy();
    feed(on.holder, egress("cloud_tier", "started", "Cloud tutor"), turnId);
    expect(label()).toBe("Cloud tutor");
    expect(document.querySelector("[data-turn-egress]")?.textContent).toContain("Sending to Cloud tutor");
    expect(document.querySelector("[data-turn-egress]")?.textContent).toContain(BASE["settings.online.leaves.cloud_tier"]!);
    tutorText(on.holder, turnId, "Force is the rate of change of momentum.");
    feed(on.holder, egress("cloud_tier", "ended", "Cloud tutor"), turnId);
    endTurn(on.holder, turnId);
    expect(screen.getByText("Answered by the online tutor")).toBeTruthy();
    cleanup();

    // Cloud tier off: the indicator says everything stays here, and no turn shows an egress notice.
    const off = await runtime();
    frame(off.profiles, off.holder, <TutorScreen sessionId={SESSION} />);
    await settled("On this computer");
    const local = startTurn(off.holder);
    tutorText(off.holder, local, "Force is the rate of change of momentum.");
    endTurn(off.holder, local);
    expect(document.querySelector("[data-turn-egress]")).toBeNull();
    expect(screen.queryByText("Answered by the online tutor")).toBeNull();
    expect(screen.queryByText(/Cloud tutor|^Online$/)).toBeNull();
  });

  test("test_prd21_online_features_family_settings", async () => {
    const { core, holder, profiles } = await runtime((c) => {
      c.network = "offline";
      c.features.telemetry = true;
    }, BEN.profile_id);
    render(
      <LocaleProvider locale="en">
        <StoreProvider holder={holder} session={null}>
          <AppFrame profiles={profiles}><Settings profiles={profiles} /></AppFrame>
        </StoreProvider>
      </LocaleProvider>,
    );
    await screen.findByRole("checkbox", { name: "Easy-read text" });
    await settled("Offline");
    // The student sees the indicator and its popover, which lists the features and switches nothing.
    fireEvent.click(trigger());
    const pop = popover()!;
    expect(within(pop).getByText("Usage reports")).toBeTruthy();
    expect(within(pop).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(pop).queryAllByRole("switch")).toHaveLength(0);
    // The online-feature switches live only in Settings → Online features (TABLE UXS-46a), never elsewhere on screen.
    const names = ONLINE_FEATURES.map((f) => BASE[`settings.online.feature.${f}`]!);
    await screen.findByRole("checkbox", { name: "Usage reports" });
    for (const name of names) for (const box of screen.queryAllByRole("checkbox", { name })) expect(box.closest("[data-settings-section='online_features']")).not.toBeNull();
    expect(screen.getByText("Turn off all online features").closest("[data-settings-section='online_features']")).not.toBeNull();
    // No client-core path enables a feature without the adult token, and none sends anything.
    await profiles.family.subscription();
    expect(core.log.at(-1)!.headers["x-adult-token"]).toBeUndefined();
    expect(Object.keys(profiles.connectivity).concat(Object.getOwnPropertyNames(Object.getPrototypeOf(profiles.connectivity))).filter((k) => /enable|setOnline|subscription|patch/i.test(k))).toEqual([]);
    // Family switches require the launch credential; the removed adult header confers no authority.
    const refused = await core.fetch("http://core.test/v1/connectivity", { method: "PATCH", headers: { "x-adult-token": "obsolete" }, body: JSON.stringify({ features: { downloads: true } }) });
    expect(refused.status).toBe(401);
    expect(screen.getByRole("checkbox", { name: "Usage reports" }).closest("[data-family-group='online']")).not.toBeNull();
  });
});

describe("PRV-28", () => {
  test("prv28_pre_send_notice", () => {
    // Every DAT-18 egress path that ships at S2, file export and the LAN compute server (S4).
    expect([...PRE_SEND_PATHS].sort()).toEqual(["cloud_tier", "crash_reports", "downloads", "file_export", "lan_compute", "telemetry", "update_checks"]);
    for (const p of PRE_SEND_PATHS) {
      const states = STATES.filter((s) => s.component === "EgressNotice" && (s.payload as { path: string }).path === p);
      expect(states.length, p).toBeGreaterThan(0);
      for (const state of states) {
        const { container } = render(<GalleryView state={state} />);
        const destination = (state.payload as { destination_label: string }).destination_label;
        const text = container.textContent ?? "";
        expect(destination.trim().length, state.id).toBeGreaterThan(0);
        expect(text, state.id).toContain(`Sending to ${destination}`); // the destination, in plain words
        const leaves = BASE[p === "file_export" || p === "lan_compute" ? `egress.leaves.${p}` : `settings.online.leaves.${p}`];
        expect(leaves, p).toBeTruthy();
        expect(text, state.id).toContain(leaves!); // the data, in plain words
        cleanup();
      }
    }
    // The first-use notice of a feature (ARC-10) renders with its own two answers.
    const first = STATES.find((s) => s.component === "ConfirmCard" && (s.payload as { purpose: string }).purpose === "egress")!;
    render(<GalleryView state={first} />);
    expect(screen.getByRole("button", { name: "OK" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Keep it on this computer" })).toBeTruthy();
  });
});
