// VOC-18 in Settings → Voice: the system voices are listed best first, and when every installed English voice is a
// compact one, one line says how to add a better system voice. Over fake voice lists; no network voice is listed.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { LocaleProvider } from "@jana/ui";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { VoiceSettings } from "../src/VoiceSettings.js";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const voice = (voiceURI: string, name: string, localService = true) => ({ voiceURI, name, lang: "en-GB", localService, default: false });

function withVoices(voices: ReturnType<typeof voice>[]) {
  vi.stubGlobal("speechSynthesis", { getVoices: () => voices, addEventListener: vi.fn(), removeEventListener: vi.fn(), speak: vi.fn(), cancel: vi.fn() });
  const core = new FakeProfileCore();
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  render(<LocaleProvider locale="en"><VoiceSettings profiles={profiles} /></LocaleProvider>);
}

const HINT = /add an enhanced or premium voice/;

describe("VOC-18", () => {
  test("only compact voices: the line on adding a better system voice", () => {
    withVoices([voice("a", "Daniel"), voice("b", "Karen"), voice("net", "Online voice (Natural)", false)]);
    expect(screen.getByText(HINT)).toBeTruthy();
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Automatic", "Daniel (en-GB)", "Karen (en-GB)"]);
  });

  test("a natural voice installed: listed first, and no line", () => {
    withVoices([voice("a", "Daniel"), voice("b", "Serena (Enhanced)")]);
    expect(screen.queryByText(HINT)).toBeNull();
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Automatic", "Serena (Enhanced) (en-GB)", "Daniel (en-GB)"]);
  });
});
