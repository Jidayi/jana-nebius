// D130: the voice conversation lives in the open chats (Ask anything on Home, a study set's Chat tab); the tutor screen
// keeps read-aloud and dictation but shows no voice bar (UXS-34, VOC-53).
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { LocaleProvider } from "@jana/ui";
import { FakeProfileCore, PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { SpeechTools } from "../src/SpeechTools.js";

afterEach(() => cleanup());

async function shown(place: NonNullable<Parameters<typeof SpeechTools>[0]["place"]> | null) {
  const core = new FakeProfileCore();
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch.bind(core) as typeof fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  render(<LocaleProvider locale="en"><SpeechTools sessionId="ses_01JZ0000000000000000000001" launch={core.launch} holder={new StoreHolder()}
    voice={{ pack: true, dictation: true, talk: true }} profiles={profiles} place={place}><p>Screen</p></SpeechTools></LocaleProvider>);
  await screen.findByText("Screen");
}

test("uxs34_voice_bar_in_open_chats: Ask anything and the study Chat tab have the voice bar, the tutor screen has none", async () => {
  await shown({ place: "ask" });
  await waitFor(() => expect(screen.getByRole("button", { name: /Start a conversation/i })).toBeTruthy());
  cleanup();
  await shown({ place: "study", source_id: "src_01JZ0000000000000000000001", revision: 1, open: "" });
  await waitFor(() => expect(screen.getByRole("button", { name: /Start a conversation/i })).toBeTruthy());
  cleanup();
  await shown(null); // the tutor screen: read-aloud and dictation only
  expect(screen.queryByRole("button", { name: /Start a conversation/i })).toBeNull();
});
