import { useEffect, useMemo, useState } from "react";
import type { ProfileController } from "@jana/client-core";
import { useProfiles, useT } from "@jana/ui";
import { BrowserLocalSpeech } from "./local-speech.js";

export function VoiceSettings({ profiles }: { profiles: ProfileController }) {
  const t = useT(), profile = useProfiles(profiles), local = useMemo(() => new BrowserLocalSpeech(), []);
  const [voices, setVoices] = useState(() => local.voices()), [error, setError] = useState(false);
  const [compact, setCompact] = useState(() => local.onlyCompact());
  useEffect(() => local.subscribe(() => { setVoices(local.voices()); setCompact(local.onlyCompact()); }), [local]);
  const settings = profile.settings;
  const change = (patch: { speech_rate?: number; speech_voice?: string }) => {
    setError(false); void profiles.setPreferences(patch).catch(() => setError(true));
  };
  return <section aria-labelledby="voice-settings" className="flex flex-col gap-3">
    <h2 id="voice-settings" className="text-ui font-semibold">{t("voice.settings")}</h2>
    <label>{t("voice.rate")} <input aria-label={t("voice.rate")} type="range" min="0.75" max="1.5" step="0.05"
      value={settings?.speech_rate ?? 1} onChange={(e) => change({ speech_rate: Number(e.target.value) })} /> {settings?.speech_rate ?? 1}×</label>
    <label>{t("voice.local_voice")} <select value={settings?.speech_voice ?? ""} onChange={(e) => change({ speech_voice: e.target.value })}>
      <option value="">{t("voice.automatic_voice")}</option>
      {voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}
    </select></label>
    <p className="text-meta text-muted">{t("voice.voice_scope")}</p>
    {compact && <p className="text-meta text-muted" data-better-voice="">{t("voice.better_voice")}</p>}
    {error && <p role="status">{t("notes.failed")}</p>}
  </section>;
}
