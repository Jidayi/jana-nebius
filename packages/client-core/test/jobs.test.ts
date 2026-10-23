import { afterEach, expect, test, vi } from "vitest";
import { waitForJob } from "../src/jobs.js";
import { CommandClient } from "../src/stream/commands.js";

const id = "job_00000000000000000000000090";
const done = { job_id: id, kind: "import", state: "done", progress: null, result_ref: "prf_00000000000000000000000099", error: null };
function client(read: () => unknown) {
  return new CommandClient({ endpoint: async () => ({ baseUrl: "http://local", token: "synthetic", headers: {} }),
    fetch: async () => new Response(JSON.stringify(read())) });
}
afterEach(() => vi.useRealTimers());

test("accepted work waits through queued and running states", async () => {
  vi.useFakeTimers();
  const states = ["queued", "running", "done"];
  const read = vi.fn(() => ({ ...done, state: states.shift() }));
  const result = waitForJob(client(read), id);
  await vi.advanceTimersByTimeAsync(500);
  await expect(result).resolves.toEqual(done);
  expect(read).toHaveBeenCalledTimes(3);
});

test("a cancelled job cannot be reported as success", async () => {
  await expect(waitForJob(client(() => ({ ...done, state: "cancelled" })), id)).rejects.toMatchObject({ code: "internal_error" });
});

test("a different job or malformed reply cannot complete the requested work", async () => {
  await expect(waitForJob(client(() => ({ ...done, job_id: "job_00000000000000000000000091" })), id)).rejects.toMatchObject({ code: "invalid_reply" });
  await expect(waitForJob(client(() => ({})), id)).rejects.toMatchObject({ code: "invalid_reply" });
});

test("closing the owner stops polling", async () => {
  vi.useFakeTimers();
  const controller = new AbortController(), read = vi.fn(() => ({ ...done, state: "running" }));
  const result = waitForJob(client(read), id, controller.signal);
  const rejection = expect(result).rejects.toMatchObject({ name: "AbortError" });
  await vi.advanceTimersByTimeAsync(0);
  controller.abort();
  await rejection;
  await vi.advanceTimersByTimeAsync(1000);
  expect(read).toHaveBeenCalledOnce();
});
