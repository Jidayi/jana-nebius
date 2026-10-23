import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeProfileCore, PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { pickProfileArchive } from "../src/launch.js";

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("prefers-color-scheme"), media: query, addEventListener() {}, removeEventListener() {} })));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const JOB = "job_00000000000000000000000090";
const RESTORED = "prf_00000000000000000000000099";
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function start(firstRun = false) {
  const core = new FakeProfileCore();
  if (firstRun) core.profiles.splice(0);
  let path: string | null = "/synthetic/student.janaprofile";
  const invoke = vi.fn(async (name: string) => { expect(name).toBe("pick_profile_archive"); return path; });
  vi.stubGlobal("__TAURI_INTERNALS__", { invoke });
  let fail: "archive" | "job" | null = null, running = false, reads = 0;
  const imports: unknown[] = [];
  const fetcher = (async (input, init) => {
    if (init?.method === "POST" && String(input).endsWith("/v1/profiles/import")) {
      const body = JSON.parse(String(init.body)); imports.push(body);
      if (fail === "archive") return json({ error: { code: "archive_invalid", retryable: false } }, 422);
      if (!core.profiles.some((p) => p.profile_id === RESTORED)) core.profiles.push({ ...PROFILES[0]!, profile_id: RESTORED, display_name: "Restored Ada" });
      return json({ job_id: JOB, queued_until_online: false }, 202);
    }
    if (String(input).endsWith(`/v1/jobs/${JOB}`)) {
      reads += 1;
      return json({ job_id: JOB, kind: "import", state: fail === "job" ? "failed" : running && reads === 1 ? "running" : "done", result_ref: fail === "job" ? null : RESTORED, progress: null, error: null });
    }
    return core.fetch(input, init);
  }) as typeof fetch;
  const runtime = createRuntime(core.launch, fetcher); runtime.chooseArchive = pickProfileArchive;
  render(<App runtime={runtime} />);
  return { core, invoke, imports, path: (next: string | null) => { path = next; }, fail: (next: typeof fail) => { fail = next; }, running: () => { running = true; } };
}

const restoreOptions = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "Restore from a profile archive" }));
  // Chosen from a working picker, restoring is its own flow, not the broken-store recovery (no "Try again").
  await screen.findByRole("heading", { name: "Restore a profile" });
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
};
const choose = async () => {
  fireEvent.click(screen.getByRole("button", { name: "Choose an archive" }));
  return screen.findByLabelText("The archive's passphrase");
};
const submit = async () => {
  const field = await choose(); fireEvent.change(field, { target: { value: "synthetic passphrase" } });
  fireEvent.click(screen.getByRole("button", { name: "Restore from a profile archive" }));
};

test("archive restore uses the native capability, waits for its job, and preserves existing profiles", async () => {
  const s = start(); s.running(); const before = s.core.profiles.map((p) => ({ ...p }));
  await restoreOptions(); await submit();
  await screen.findByText("The profile is back. Choose it to carry on.");
  expect(s.invoke).toHaveBeenCalledWith("pick_profile_archive");
  expect(s.imports).toEqual([{ source: { kind: "file", path: "/synthetic/student.janaprofile" }, passphrase: "synthetic passphrase" }]);
  expect(s.core.profiles.slice(0, before.length)).toEqual(before);
  expect(document.querySelector("input[type=password]")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Go to the profiles" }));
  await screen.findByRole("button", { name: /Restored Ada/ });
});

test("cancelled picker keeps recovery usable and starts no import", async () => {
  const s = start(); s.path(null); await restoreOptions();
  fireEvent.click(screen.getByRole("button", { name: "Choose an archive" }));
  await waitFor(() => expect(s.invoke).toHaveBeenCalledOnce());
  expect(s.imports).toEqual([]); expect(screen.queryByLabelText("The archive's passphrase")).toBeNull();
  s.path("/synthetic/other.janaprofile"); await choose();
});

test.each(["archive", "job"] as const)("failed %s can choose another file and recover", async (kind) => {
  const s = start(); s.fail(kind); await restoreOptions(); await submit();
  await screen.findByRole("button", { name: "Choose another file" });
  expect(screen.queryByText("The profile is back. Choose it to carry on.")).toBeNull();
  s.fail(null); fireEvent.click(screen.getByRole("button", { name: "Choose another file" }));
  const field = await screen.findByLabelText("The archive's passphrase"); expect((field as HTMLInputElement).value).toBe("");
  fireEvent.change(field, { target: { value: "correct synthetic passphrase" } });
  fireEvent.click(screen.getByRole("button", { name: "Restore from a profile archive" }));
  await screen.findByText("The profile is back. Choose it to carry on.");
});

test("a new installation can restore without creating a replacement student first", async () => {
  const s = start(true); await restoreOptions(); await submit();
  await screen.findByText("The profile is back. Choose it to carry on.");
  fireEvent.click(screen.getByRole("button", { name: "Go to the profiles" }));
  await screen.findByRole("button", { name: /Restored Ada/ });
  expect(s.core.profiles).toHaveLength(1);
});
