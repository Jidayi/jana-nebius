// @vitest-environment node
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import path from "node:path";
import { tmpdir } from "node:os";
import { expect, test } from "vitest";
// @ts-expect-error Browser-only verification helper has no public TypeScript API.
import { fixtureServer } from "../../../scripts/ci/browser-fixtures.mjs";
test("browser journeys retain an immutable build while another process rebuilds the output", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "jana-fixture-server-"));
  await mkdir(path.join(root, "assets")); await writeFile(path.join(root, "gallery.html"), '<script src="/assets/entry.js"></script>');
  await writeFile(path.join(root, "assets/entry.js"), "original build");
  const server = await fixtureServer({ root });
  try {
    await rm(root, { recursive: true });
    expect(await (await fetch(`${server.url}/gallery.html`)).text()).toContain("/assets/entry.js");
    const asset = await fetch(`${server.url}/assets/entry.js`); expect(asset.status).toBe(200); expect(await asset.text()).toBe("original build");
    expect((await fetch(`${server.url}/missing.js`)).status).toBe(404);
  } finally { await server.close(); await rm(root, { recursive: true, force: true }); }
});
