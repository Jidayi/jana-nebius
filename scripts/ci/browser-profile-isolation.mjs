// Synthetic Chromium heap regression; not reference-device or independent security qualification.
import { chromium } from "playwright";
import { createServer } from "../../apps/desktop/node_modules/vite/dist/node/index.js";
import react from "../../apps/desktop/node_modules/@vitejs/plugin-react/dist/index.js";
import tailwindcss from "../../apps/desktop/node_modules/@tailwindcss/vite/dist/index.mjs";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const seeded = process.argv.includes("--retain-profile");
const out = path.resolve(process.argv[2] ?? "dist/browser-profile-isolation");
await mkdir(out, { recursive: true });
const server = await createServer({ root: path.resolve("apps/desktop"), configFile: false, plugins: [react(), tailwindcss()], server: { host: "127.0.0.1", port: 0 } });
await server.listen();
const { FakeProfileCore, PROFILES } = await server.ssrLoadModule(path.resolve("packages/client-core/test/profilecore.ts"));
PROFILES[0].canary = `PRIVATE_${randomUUID().replaceAll("-", "")}_TRANSCRIPT`;
const needle = PROFILES[0].canary;
const core = new FakeProfileCore();
for (const p of PROFILES) core.sessionsMade.set(p.session_id, { subject: "physics", topic_id: null });
core.packs.push({ pack_id: "pack.phy.o", subject: "physics", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
const browser = await chromium.launch();
const page = await browser.newPage();
page.setDefaultTimeout(15000);
try {
  await page.route("http://core.test/**", async (route) => {
    const request = route.request();
    if (request.url().endsWith("/events")) { await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" }); return; }
    if (request.url().endsWith("/journal")) { await route.fulfill({ json: { snapshot: null, envelopes: [] } }); return; }
    const response = await core.fetch(request.url(), { method: request.method(), headers: request.headers(), body: request.postData() });
    await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers), body: Buffer.from(await response.arrayBuffer()) });
  });
  const base = server.resolvedUrls.local[0];
  await page.goto(`${base}gallery.html?benchmark=profile-isolation`);
  await page.getByRole("button", { name: "Ada", exact: true }).click();
  await page.locator('[data-isolation-ready="yes"]').waitFor();
  if (!(await page.locator("body").textContent()).includes(needle)) throw new Error("Canary never reached the DOM");
  const cdp = await page.context().newCDPSession(page);
  async function heap() {
    const chunks = []; const receive = ({ chunk }) => chunks.push(chunk);
    cdp.on("HeapProfiler.addHeapSnapshotChunk", receive);
    await cdp.send("HeapProfiler.collectGarbage");
    await cdp.send("HeapProfiler.takeHeapSnapshot", { reportProgress: false });
    cdp.off("HeapProfiler.addHeapSnapshotChunk", receive);
    return JSON.parse(chunks.join(""));
  }
  const before = await heap();
  if (!before.strings.some((s) => s.includes(needle))) throw new Error("Canary never reached the heap");
  if (seeded) await page.evaluate(() => { globalThis.__deliberateProfileLeak = globalThis.document.body.textContent; });
  await page.getByRole("button", { name: "Ben", exact: true }).click();
  await page.locator('[data-isolation-ready="yes"]').waitFor();
  await page.waitForTimeout(100); // React passive unmount cleanup
  const after = await heap();
  const strings = after.strings.filter((s) => s.includes(needle));
  const domLeaks = (await page.locator("body").textContent()).includes(needle);
  const result = { test: "uia08_no_cross_profile_residue", browser: browser.version(), before_present: true, seeded_leak: seeded, after_string_count: strings.length, dom_leak: domLeaks, synthetic: true, native_webview: false, independent_review: false };
  await writeFile(path.join(out, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  if ((!seeded && (strings.length || domLeaks)) || (seeded && strings.length === 0)) {
    await writeFile(path.join(out, "leaking-heap.json"), JSON.stringify(after));
    throw new Error(`Profile A remains in ${strings.length} heap strings after switching`);
  }
} finally { await browser.close(); await server.close(); }
