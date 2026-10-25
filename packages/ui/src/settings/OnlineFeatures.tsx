// Settings → Online features, inside family settings (UXS-07, ARC-11): one row per feature the core lists for this
// stage, in the order of TABLE ARC-07a, each saying what leaves this computer and what happens offline (TABLE
// UXS-07a), all off on a fresh install, and "Turn off all online features". A switch is the feature's only setting
// (D53). Turning one on asks first, naming the data; for a feature that sends learner or usage data the confirmation
// also shows its consent line (PRV-05) and the guardian attestation (PRV-06), and "Turn on" records the consent with the
// switch (the core does both in `PATCH /v1/connectivity`); turning it off withdraws the consent. Downloads and update
// checks need only the switch. The cloud tutor is not a switch (D70): subscribing turns it on, the guardian's consent
// for each profile under 18 is recorded with it, and ending the subscription turns it off.
import { useEffect, useState } from "react";
import {
  CONSENT_FEATURES, CONSENT_NOTICE_VERSIONS, ONLINE_FEATURES, type FamilySettings, type CloudSubscription, type ConnectivityReply,
  agreesForItself, readProfile, readConsents, switchConsent, type ConsentState, type ProfileController,
} from "@jana/client-core";
import type { OnlineFeature } from "@jana/contracts-ts";
import { useT } from "../i18n.js";
import { Button, ConfirmDialog, Skeleton } from "../primitives/index.js";
import { useProfiles } from "../profiles/ProfilePicker.js";

type Run = (work: () => Promise<unknown>) => void;
type Sub = CloudSubscription | "loading" | "failed";

function Cloud({ subscription, names, selfConsent, onConsent, onEnd }: { subscription: Sub; names: string[]; selfConsent: boolean; onConsent: () => void; onEnd: () => void }) {
  const t = useT();
  if (subscription === "loading") return <Skeleton lines={1} />;
  if (subscription === "failed") return <p className="text-ui text-ink">{t("settings.online.cloud.unavailable")}</p>;
  if (subscription.state === "active") {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-ui text-ink">{t("settings.online.cloud.active")}</p>
        {subscription.period_end !== null && <p className="text-meta text-muted">{t("settings.online.cloud.period_end", { end: new Date(subscription.period_end) })}</p>}
        {subscription.allowance_used_up && <p className="text-meta text-muted">{t("settings.online.cloud.allowance_used_up")}</p>}
        <div>
          <Button onClick={onEnd}>{t("settings.online.cloud.turn_off")}</Button>
        </div>
      </div>
    );
  }
  if (subscription.state === "pending_consent") {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-ui text-ink">{t(selfConsent ? "settings.online.cloud.pending_self" : "settings.online.cloud.pending", { names: names.join(", ") })}</p>
        <div>
          <Button tone="primary" onClick={onConsent}>{t("settings.online.cloud.give_consent")}</Button>
        </div>
      </div>
    );
  }
  return <p className="text-ui text-ink">{t("settings.online.cloud.off")}</p>;
}

export function OnlineFeatures({ profiles, run }: { profiles: ProfileController; run: Run }) {
  const t = useT();
  const family: FamilySettings = profiles.family;
  const view = useProfiles(profiles);
  const known = view.profiles;
  const [adult, setAdult] = useState(false);
  const [studyConsent, setStudyConsent] = useState<ConsentState | null>(null);
  const [cloudConsent, setCloudConsent] = useState<ConsentState | null>(null);
  const [state, setState] = useState<ConnectivityReply | null>(null);
  const [subscription, setSubscription] = useState<Sub>("loading");
  const [asking, setAsking] = useState<OnlineFeature | null>(null);
  const [dialog, setDialog] = useState<"consent" | "end" | "all_off" | null>(null);
  useEffect(() => {
    family.connectivity().then(setState, () => setState(null));
    family.subscription().then(setSubscription, () => setSubscription("failed"));
  }, [family]);
  useEffect(() => {
    let live = true;
    setAdult(false);
    setStudyConsent(null);
    setCloudConsent(null);
    if (view.active !== null) {
      readConsents(profiles.commands, view.active).then(
        (consents) => { if (live) {
          setStudyConsent(consents.find((c) => c.scope === "study_materials") ?? null);
          setCloudConsent(consents.find((c) => c.scope === "cloud_tier") ?? null);
        } }, () => undefined,
      );
      readProfile(profiles.commands, view.active).then(
        (profile) => live && setAdult(agreesForItself(profile)), () => undefined,
      );
    }
    return () => { live = false; };
  }, [profiles, view.active]);
  if (state === null) return <Skeleton lines={2} />;

  const listed = ONLINE_FEATURES.filter((f) => state.features[f] !== undefined);
  const switches = listed.filter((f) => f !== "cloud_tier");
  const active = subscription !== "loading" && subscription !== "failed" && subscription.state === "active";
  const needed = subscription !== "loading" && subscription !== "failed" ? subscription.profiles.filter((p) => p.consent === "needed").map((p) => p.profile_id) : [];
  const names = needed.map((id) => known.find((p) => p.profile_id === id)?.display_name ?? "").filter((n) => n !== "");
  const selfConsent = adult && needed.length > 0 && needed.every((id) => id === view.active);
  const studyNeedsCloud = adult && (!cloudConsent?.effective || cloudConsent.paused || (view.active !== null && needed.includes(view.active)));
  const set = (change: Partial<Record<OnlineFeature, boolean>>) => run(async () => setState(await family.setOnlineFeatures(change)));
  const refresh = async () => setState(await family.connectivity());
  const end = () => run(async () => {
    setSubscription(await family.endSubscription());
    await refresh();
  });
  const allOff = () => run(async () => {
    if (switches.length > 0) setState(await family.setOnlineFeatures(Object.fromEntries(switches.map((f) => [f, false]))));
    if (active) {
      setSubscription(await family.endSubscription());
      await refresh();
    }
  });

  return (
    <>
      {listed.map((feature) => (
        <div key={feature} data-online-feature={feature} className="flex flex-col gap-1 border-t border-line pt-2">
          {feature === "cloud_tier" ? (
            <p className="text-ui font-semibold text-ink">{t(`settings.online.feature.${feature}`)}</p>
          ) : (
            <label className="flex items-center gap-2 text-ui font-semibold text-ink">
              <input
                type="checkbox"
                checked={state.features[feature]?.enabled ?? false}
                onChange={(event) => (event.target.checked ? setAsking(feature) : set({ [feature]: false }))}
              />
              {t(`settings.online.feature.${feature}`)}
            </label>
          )}
          <p className="text-meta text-muted">{t("settings.online.leaves_label")} {t(`settings.online.leaves.${feature}`)}</p>
          <p className="text-meta text-muted">{t("settings.online.offline_label")} {t(`settings.online.offline.${feature}`)}</p>
          {feature === "study_materials" && (!studyConsent?.effective || studyConsent.paused || studyNeedsCloud || (!adult && studyConsent.method !== "checkout_guardian")) && <div className="flex flex-col items-start gap-2">
            <p className="text-ui text-ink">{t(adult ? "study.access.settings_self" : "study.access.settings_guardian")}</p>
            {adult && <Button onClick={() => setAsking("study_materials")}>{t("study.access.review_consent")}</Button>}
          </div>}
          {feature === "cloud_tier" && <Cloud subscription={subscription} names={names} selfConsent={selfConsent} onConsent={() => setDialog("consent")} onEnd={() => setDialog("end")} />}
        </div>
      ))}
      <div className="border-t border-line pt-2">
        <Button onClick={() => (active ? setDialog("all_off") : allOff())}>{t("settings.online.all_off")}</Button>
      </div>
      <ConfirmDialog
        open={asking !== null}
        message={asking === null ? "" : t("settings.online.confirm", { feature: t(`connectivity.short.${asking}`) })}
        details={asking === null ? [] : [
          t(`settings.online.leaves.${asking}`),
          ...(asking === "study_materials" && studyNeedsCloud ? [t("settings.online.consent.cloud_tier")] : []),
          ...(CONSENT_FEATURES.has(asking) ? [t(`settings.online.consent.${asking}`), t(adult ? "settings.online.self_attestation" : "settings.online.attestation")] : []),
        ]}
        confirm={t("settings.online.turn_on")}
        cancel={t("action.cancel")}
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          const feature = asking;
          setAsking(null);
          if (feature !== null) run(async () => {
            // The device switch alone is not profile consent. Adults can grant
            // their own through the existing consent API; minors keep the
            // signed guardian-checkout requirement enforced by the core.
            if (feature === "study_materials" && adult && view.active !== null) {
              if (needed.includes(view.active)) {
                setSubscription(await family.applySubscription({ entitlement: {}, consents: [
                  { profile_id: view.active, notice_version: CONSENT_NOTICE_VERSIONS.cloud_tier },
                ] }));
              }
              setStudyConsent(await switchConsent(profiles.commands, view.active, feature, "on"));
              if (studyNeedsCloud) setCloudConsent(await switchConsent(profiles.commands, view.active, "cloud_tier", "on"));
            }
            setState(await family.setOnlineFeatures({ [feature]: true }));
          });
        }}
      />
      <ConfirmDialog
        open={dialog === "consent"}
        message={t("settings.online.cloud.confirm")}
        details={[t("settings.online.consent.cloud_tier"), t(selfConsent ? "settings.online.self_attestation" : "settings.online.attestation")]}
        confirm={t("settings.online.turn_on")}
        cancel={t("action.cancel")}
        onCancel={() => setDialog(null)}
        onConfirm={() => {
          setDialog(null);
          // The entitlement is the one the checkout left with the core, waiting for these consents (D70).
          const consents = needed.map((profile_id) => ({ profile_id, notice_version: CONSENT_NOTICE_VERSIONS.cloud_tier }));
          run(async () => {
            setSubscription(await family.applySubscription({ entitlement: {}, consents }));
            await refresh();
          });
        }}
      />
      <ConfirmDialog
        open={dialog === "end" || dialog === "all_off"}
        message={dialog === "all_off" ? t("settings.online.all_off_confirm") : t("settings.online.cloud.end_confirm")}
        confirm={t("settings.online.turn_off")}
        cancel={t("action.cancel")}
        onCancel={() => setDialog(null)}
        onConfirm={() => {
          const which = dialog;
          setDialog(null);
          if (which === "all_off") allOff();
          else end();
        }}
      />
    </>
  );
}
