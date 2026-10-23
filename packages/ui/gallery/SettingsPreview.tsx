// The real Settings page against an in-memory synthetic core; no gallery request leaves this process.
import { useEffect, useMemo, useState } from "react";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { Settings } from "../src/settings/Settings.js";
import { ErrorState, Skeleton } from "../src/primitives/index.js";
import { useT } from "../src/i18n.js";

export function SettingsPreview({ state }: { state: string }) {
  const t = useT(); const [ready, setReady] = useState(false);
  const profiles = useMemo(() => { const core = new FakeProfileCore(); return new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch }); }, []);
  useEffect(() => {
    let closed = false;
    void (async () => { await profiles.load(); await profiles.unlock(PROFILES[0]?.profile_id ?? ""); if (!closed) setReady(true); })();
    return () => { closed = true; void profiles.lock(); };
  }, [profiles]);
  if (state === "error-retriable") return <ErrorState message={t("error.core_starting")} action={{ label: t("action.try_again"), onClick: () => undefined }} />;
  if (state === "loading" || !ready) return <div role="status" aria-busy="true"><span className="sr-only">{t("settings.loading")}</span><Skeleton lines={3} /></div>;
  return <Settings profiles={profiles} onClose={() => undefined} onOpenKnows={() => undefined} />;
}
