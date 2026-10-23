import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SessionController, StoreHolder, typedCapture } from "@jana/client-core";
import { CaptureDiagrams } from "../src/composer/CaptureDiagrams.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
const SID = `ses_${"0".repeat(26)}`;
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
test("inp26_diagram_values_confirmed: show the local original crop with confirmed edited text and release it", async () => {
 const reads: string[] = [], holder = new StoreHolder();
 const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, SID, { fetch: async (url) => { reads.push(String(url)); return new Response(new Blob(["synthetic masked crop"], { type: "image/jpeg" })); } });
 const capture = { ...typedCapture("Find c; Side a = 6 cm; Side b = 4 cm.", { sessionId: SID, confirmed: true }), attachments: [{ image_id: `img_${"0".repeat(26)}`, kind: "diagram_crop" as const, width: 100, height: 100, bytes: 20, sha256: "a".repeat(64) }] };
 const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:confirmed-crop"), revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
 const view = render(<LocaleProvider locale="en"><StoreProvider holder={holder} session={session}><CaptureDiagrams capture={capture} /></StoreProvider></LocaleProvider>);
 try {
  await waitFor(() => expect(screen.getByRole("img", { name: capture.text }).getAttribute("src")).toBe("blob:confirmed-crop"));
  expect(reads).toEqual([`http://core.test/v1/captures/${capture.capture_id}/images/${capture.attachments[0]!.image_id}`]);
  expect(view.container.textContent).toContain("Side a = 6 cm"); expect(view.container.textContent).not.toContain("Side a = 3 cm");
  view.rerender(<LocaleProvider locale="en"><StoreProvider holder={holder} session={session}><CaptureDiagrams capture={{ ...capture, status: "awaiting_confirmation", confirmation: { ...capture.confirmation, confirmed: false } }} /></StoreProvider></LocaleProvider>);
  expect(screen.queryByRole("img")).toBeNull(); expect(revoke).toHaveBeenCalledWith("blob:confirmed-crop"); expect(create).toHaveBeenCalledOnce();
 } finally { view.unmount(); session.close(); }
});
