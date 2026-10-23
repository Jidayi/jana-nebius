import { describe, expect, test } from "vitest";
import { InstallationController } from "../src/installations.js";
import { CommandClient } from "../src/stream/commands.js";

describe("desktop installation commands", () => {
  test("USB update waits for its job, rereads committed state, and carries an idempotency key", async () => {
    const calls: { path: string; method: string; body: unknown; key: string | null }[] = [];
    let staged = false;
    const commands = new CommandClient({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }),
      fetch: async (url, init) => {
        const path = new URL(String(url)).pathname;
        calls.push({ path, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : null,
          key: new Headers(init?.headers).get("idempotency-key") });
        let result: unknown = {};
        if (path === "/v1/models") result = { installed: [], available: [], recommended: { fast: null, strong: null, reason_key: "no_class.no_model_manifest" } };
        else if (path === "/v1/updates/install") result = { job_id: "job_synthetic", queued_until_online: false };
        else if (path === "/v1/jobs/job_synthetic") { staged = true; result = { state: "done", error: null }; }
        else if (path === "/v1/updates") result = { installed_version: "1.0.0", channel: "stable", checks: "usb_or_school_only",
          staged: staged ? { version: "1.1.0", size_bytes: 2000, changes: ["Synthetic fixes"] } : null, rollback_offered: null };
        return new Response(JSON.stringify(result), { status: 200 });
      } });
    const controller = new InstallationController(commands);
    await controller.install("update", "/synthetic-usb/update.janaupdate");
    expect(controller.view.get().pending).toBe(false);
    expect(controller.view.get().updates?.staged?.version).toBe("1.1.0");
    const request = calls.find((c) => c.path === "/v1/updates/install")!;
    expect(request.body).toEqual({ source: { kind: "file", path: "/synthetic-usb/update.janaupdate" } });
    expect(request.key).toMatch(/^cli_[0-9A-HJKMNP-TV-Z]{26}$/);
    expect(calls.filter((c) => c.path === "/v1/updates")).toHaveLength(2);
  });

  test("failed verification is shown and concurrent actions cannot enqueue a second command", async () => {
    let resolve!: () => void;
    const held = new Promise<void>((done) => { resolve = done; });
    let posts = 0;
    const commands = new CommandClient({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }),
      fetch: async (url, init) => {
        if (init?.method === "POST") { posts += 1; await held; return new Response(JSON.stringify({ job_id: "job_bad" })); }
        const path = new URL(String(url)).pathname;
        return new Response(JSON.stringify(path.startsWith("/v1/jobs/") ? { state: "failed", error: { code: "validation_failed" } } : {}));
      } });
    const controller = new InstallationController(commands);
    const first = controller.install("update", "/synthetic-usb/forged.janaupdate");
    await controller.install("update", "/synthetic-usb/another.janaupdate");
    resolve();
    await first;
    expect(posts).toBe(1);
    expect(controller.view.get().pending).toBe(false);
    expect(controller.view.get().error).toBe("validation_failed");
  });
});
