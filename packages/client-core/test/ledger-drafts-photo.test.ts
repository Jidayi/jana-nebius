import journalTextGolden from "../../ui/gallery/journal-text-golden.json";
import journalGolden from "../../ui/gallery/journal-entry-golden.json";
import { afterEach, expect, test, vi } from "vitest";
import { DraftController, checkPhotoHeader, journalFromText, ledgerTable, ledgerTotals, PhotoCommands } from "../src/index.js";
import { CommandClient } from "../src/stream/commands.js";
const client = (fetch: typeof globalThis.fetch) => new CommandClient({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic-launch", headers: { "x-profile-token": "synthetic-profile" } }), fetch });
afterEach(() => vi.useRealTimers());

test("journals preserve exact pennies, negative amounts, currencies and structured fallback", () => {
  const journal = journalFromText("Dr Equipment 5000; Cr Cash 2500; Cr Payables 2500");
  expect(journal?.rows).toHaveLength(3);
  expect(journal === null ? null : ledgerTotals(journal)).toEqual({ dr: "5000", cr: "5000", currency: "USD" });
  expect(ledgerTotals(ledgerTable("trial_balance", [["Cash", "£10", ""], ["Sales", "", "10"]]))).toEqual({ dr: "10", cr: "10", currency: "GBP" });
  const small = ledgerTable("trial_balance", [["Cash", "$0.10", ""], ["Sales", "", "0.30"], ["Returns", "(0.20)", ""]]);
  expect(ledgerTotals(small)).toEqual({ dr: "-0.1", cr: "0.3", currency: "USD" });
  expect(small.text_fallback).toContain("Account | Dr | Cr\nCash | $0.10 | ");
  expect(() => ledgerTotals(ledgerTable("trial_balance", [["Cash", "$1", "€1"]]))).toThrow("ledger_currency");
});

test("a slow restore never replaces text entered meanwhile; saves follow server revisions", async () => {
  let resolve: (response: Response) => void = () => undefined;
  const bodies: Record<string, unknown>[] = [];
  const commands = client(async (_url, init) => {
    if (init?.method === "GET") return new Promise<Response>((r) => { resolve = r; });
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>; bodies.push(body);
    return new Response(JSON.stringify({ document: body.document, revision: 5, updated_at: 1 }));
  });
  const restore = vi.fn(); const failed = vi.fn();
  const drafts = new DraftController(commands, "/draft", restore, failed);
  const opening = drafts.open();
  await Promise.resolve();
  drafts.change({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "new typing" }] }] });
  resolve(new Response(JSON.stringify({ revision: 4, document: { type: "doc" } })));
  await opening; await drafts.flush();
  expect(restore).not.toHaveBeenCalled();
  expect(bodies[0]?.expected_revision).toBe(4);
  expect(failed).not.toHaveBeenCalled();
  drafts.close();
});

test("closed draft controllers discard delayed restores and unsaved buffers", async () => {
  let resolve: (response: Response) => void = () => undefined;
  const fetch = vi.fn(async () => new Promise<Response>((r) => { resolve = r; }));
  const restore = vi.fn();
  const drafts = new DraftController(client(fetch), "/draft", restore, vi.fn());
  const opening = drafts.open(); await Promise.resolve();
  drafts.change({ type: "doc" }); drafts.close();
  resolve(new Response(JSON.stringify({ revision: 1, document: { type: "doc" } })));
  await opening; await drafts.flush();
  expect(restore).not.toHaveBeenCalled(); expect(fetch).toHaveBeenCalledTimes(1);
});

test("multipart and image requests carry authentication in headers and never token URLs", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const commands = client(async (url, init) => {
    calls.push({ url: String(url), ...(init === undefined ? {} : { init }) });
    return init?.method === "GET" ? new Response(new Blob(["safe synthetic derivative"], { type: "image/jpeg" })) : new Response(JSON.stringify({ capture_id: "synthetic" }));
  });
  const photos = new PhotoCommands(commands, "ses_synthetic");
  await photos.create(new Blob(["synthetic"], { type: "image/png" }), "photo_file", "question");
  const upload = calls[0];
  expect(upload?.init?.body).toBeInstanceOf(FormData);
  expect(new Headers(upload?.init?.headers).get("content-type")).toBeNull();
  expect(new Headers(upload?.init?.headers).get("x-profile-token")).toBe("synthetic-profile");
  const blob = await photos.image("cap_synthetic", "img_synthetic");
  expect(await blob.text()).toBe("safe synthetic derivative");
  expect(calls.every((call) => !call.url.includes("token"))).toBe(true);
});


test("encoded dimensions reject oversized previews before the browser decodes pixels", async () => {
  const png = new Uint8Array(24); const header = new DataView(png.buffer);
  header.setUint32(0, 0x89504e47); header.setUint32(4, 0x0d0a1a0a); header.setUint32(16, 8001); header.setUint32(20, 100);
  await expect(checkPhotoHeader(new Blob([png], { type: "image/png" }))).rejects.toThrow("image_too_large");
  await expect(checkPhotoHeader(new Blob(["not really a JPEG"], { type: "image/jpeg" }))).rejects.toThrow("unsupported_format");
});


test("inp10_journal_serialise: exact three-row structured block, fallback and totals", () => {
  const block = ledgerTable("journal", journalGolden.rows);
  expect(block).toEqual(journalGolden.block);
  expect(ledgerTotals(block)).toEqual(journalGolden.totals);
});


test("inp10_text_to_journal: exact requested three-row conversion", () => {
  expect(journalFromText(journalTextGolden.source)).toEqual(journalTextGolden.block);
  expect(journalTextGolden.source).toBe("Dr Equipment 5000; Cr Cash 2500; Cr Payables 2500");
});
test("journal recognition rejects malformed, excessive and ordinary text without interrupting typing", () => {
  for (const source of ["I paid $5000", "Dr Equipment 5000; Cr Cash nope", "Dr Cash $1; Cr Sales €1x", "Dr Cash (1; Cr Sales 1",
    Array.from({ length: 60 }, () => `Dr ${"a".repeat(78)} 1234567890`).join("; ")]) expect(journalFromText(source)).toBeNull();
  expect(journalFromText(Array.from({ length: 60 }, () => `Dr ${"a".repeat(78)} 1234567890`).join("; "))).toBeNull();
  expect(journalFromText("Dr Cash $0.10; Cr Sales $0.30; Dr Returns ($0.20)" )?.rows).toEqual([
    ["", "Cash", "", "$0.10", ""], ["", "Sales", "", "", "$0.30"], ["", "Returns", "", "($0.20)", ""],
  ]);
});
