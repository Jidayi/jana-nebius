import { afterEach, expect, test, vi } from "vitest";
import { launchInfo } from "../src/launch.js";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

test("a failed host reaches recovery instead of polling forever", async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({ error: "core_failed" }, { status: 500 }));
  vi.stubGlobal("fetch", fetch);
  await expect(launchInfo()).rejects.toThrow("could not start");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("a starting host can become ready", async () => {
  vi.useFakeTimers();
  const launch = { base_url: "http://127.0.0.1:12345", token: "synthetic-test-token" };
  const fetch = vi.fn().mockResolvedValueOnce(new Response(null, { status: 503 })).mockResolvedValueOnce(Response.json(launch));
  vi.stubGlobal("fetch", fetch);
  const opened = launchInfo();
  await vi.advanceTimersByTimeAsync(200);
  await expect(opened).resolves.toEqual(launch);
});

test("a host that never becomes ready has a bounded wait", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
  const failed = expect(launchInfo()).rejects.toThrow("did not start in time");
  await vi.advanceTimersByTimeAsync(122_000);
  await failed;
});
