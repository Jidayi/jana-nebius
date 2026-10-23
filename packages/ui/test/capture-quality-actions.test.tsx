import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import { SessionController, StoreHolder, typedCapture } from "@jana/client-core";
import { PhotoCapture } from "../src/composer/PhotoCapture.js";
import { LocaleProvider } from "../src/i18n.js";
import { StoreProvider } from "../src/store.js";
const SID = `ses_${"0".repeat(26)}`;
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
test.each(["advisory", "blocking"] as const)("quality actions retain the source and gate the reader: %s", async (outcome) => {
 const reads: unknown[] = [], deletes: string[] = []; let creates = 0;
 const draft = { ...typedCapture("", { sessionId: SID, purpose: "question", confirmed: false }), source: "photo_file" as const };
 const holder = new StoreHolder(), session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, SID, { fetch: async (url, init) => {
  if (init?.method === "DELETE") { deletes.push(String(url)); return new Response(null, { status: 204 }); }
  if (String(url).endsWith("/read")) { reads.push(JSON.parse(String(init?.body))); return Response.json({ capture_id: draft.capture_id, status: "reading" }); }
  if (String(url).endsWith("/crop")) {
   const body = JSON.parse(String(init?.body));
   return Response.json(body.preview_only ? draft : { ...draft, status: "quality_failed", quality: { checks: [{ check: "blur", value: outcome === "advisory" ? 70 : 20, outcome }], overridden: false } });
  }
  if (init?.method === "POST") creates++;
  return Response.json(draft);
 } });
 vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-quality"); vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
 const file = new Blob([readFileSync(path.resolve(import.meta.dirname, "../gallery/photo-source-fixture.jpg"))], { type: "image/jpeg" });
 const view = render(<LocaleProvider locale="en"><StoreProvider holder={holder} session={session}><PhotoCapture file={file} sessionId={SID} purpose="question" onConfirmed={vi.fn()} onTyped={vi.fn()} onClose={vi.fn()} /></StoreProvider></LocaleProvider>);
 try {
  await waitFor(() => expect(screen.getByRole("button", { name: "Use this area" })).toHaveProperty("disabled", false));
  fireEvent.click(screen.getByRole("button", { name: "Use this area" }));
  await screen.findByRole("button", { name: "Retake" });
  expect(reads).toEqual([]);
  if (outcome === "advisory") {
   fireEvent.click(screen.getByRole("button", { name: "Use this photo anyway" }));
   await waitFor(() => expect(reads).toEqual([{ override_quality: true, send_to_cloud: false }]));
  } else {
   expect(screen.queryByRole("button", { name: "Use this photo anyway" })).toBeNull();
   const choose = vi.spyOn(view.container.querySelector<HTMLInputElement>('input[type="file"]')!, "click");
   fireEvent.click(screen.getByRole("button", { name: "Choose another photo" })); expect(choose).toHaveBeenCalledOnce();
   fireEvent.click(screen.getByRole("button", { name: "Retake" }));
   await waitFor(() => expect(creates).toBe(2)); expect(deletes).toHaveLength(1);
   expect(screen.getByRole("img", { name: "Photo of the question" })).toBeDefined(); expect(reads).toEqual([]);
  }
 } finally { view.unmount(); session.close(); }
});
