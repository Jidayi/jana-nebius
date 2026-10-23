// Browser journeys build independently; parallel Vite builds must never replace one another's assets.
import { rm } from "node:fs/promises";
import path from "node:path";
import { afterAll } from "vitest";

const id = `${process.pid}-${process.env.VITEST_WORKER_ID ?? "0"}`;
process.env.JANA_GALLERY_BUILD_ID = id;
afterAll(async () => {
  await rm(path.resolve(import.meta.dirname, `../dist/benchmark-${id}`), { recursive: true, force: true });
});
