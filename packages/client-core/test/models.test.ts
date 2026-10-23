// The model manager's view (UXS-11) over synthetic catalogues and app-channel download events (PLT-11).
import { describe, expect, test } from "vitest";
import type { ModelCatalogue } from "@jana/contracts-ts";
import { downloadState, modelManagerView, type ModelDownloadEvent } from "../src/index.js";

const LOW = "mp.synth.8b.q4_k_m.low";
const MID = "mp.synth.14b.q4_k_m.mid";

function catalogue(extra: Partial<ModelCatalogue> = {}): ModelCatalogue {
  return {
    installed: [{ model_pack_id: LOW, model_id: LOW, state: "installed", hardware_class: "low", size_bytes: 5_000_000_000 }],
    available: [{ model_pack_id: MID, hardware_class: "mid", size_bytes: 9_000_000_000 }],
    assignment: { fast: LOW, strong: LOW },
    recommended: { fast: MID, strong: MID, reason_key: "hardware_class.mid.measured" },
    ...extra,
  };
}

function event(state: ModelDownloadEvent["state"], bytes: number, code: string | null = null): ModelDownloadEvent {
  return { type: "model.download", download_id: `dl_${"0".repeat(26)}`, model_id: MID, state, bytes_done: bytes, bytes_total: 9_000_000_000, eta_s: 120, error_code: code };
}

describe("UXS-11 model manager view", () => {
  test("rows, recommendation and downloads off by default", () => {
    const view = modelManagerView(catalogue(), { downloadsOn: false });
    expect(view.kind).toBe("ready");
    expect(view.downloadsOff).toBe(true);
    expect(view.rows.map((r) => [r.id, r.state, r.recommended])).toEqual([[LOW, "installed", false], [MID, "available", true]]);
    expect(modelManagerView(null, { downloadsOn: true }).kind).toBe("loading");
  });

  test("below the minimum laptop nothing is recommended", () => {
    const hardware = { hardware_class: "content_only", basis: "below_minimum_ram", provisional: true, shortfalls: [{ check: "ram", have: 4, need: 8, unit: "GB" }],
      benchmark: null, benchmark_due: false, class_choice: null, tutor_path: "none", runtime: null };
    const view = modelManagerView(catalogue({ hardware } as Partial<ModelCatalogue>), { downloadsOn: true });
    expect(view.kind).toBe("below_minimum");
    expect(view.rows.some((r) => r.recommended)).toBe(false);
    expect(view.shortfalls[0]?.check).toBe("ram");
  });

  test("download events drive the row: waiting, progress, connection lost, checking, damaged, disk full", () => {
    expect(downloadState(event("queued", 0, "waiting_for_network"))).toBe("queued");
    expect(downloadState(event("queued", 3_000, "waiting_for_network"))).toBe("error_retriable");
    expect(downloadState(event("downloading", 3_000))).toBe("downloading");
    expect(downloadState(event("paused", 3_000, "storage_low"))).toBe("disk_full");
    expect(downloadState(event("verifying", 9_000))).toBe("checking");
    expect(downloadState(event("failed", 0, "model.damaged"))).toBe("error_final");
    expect(downloadState(event("failed", 0, "storage_full"))).toBe("disk_full");
    expect(downloadState(event("done", 9_000))).toBe("installed");
    const view = modelManagerView(catalogue(), { downloadsOn: true, downloads: { [MID]: event("downloading", 4_500_000_000) } });
    const row = view.rows.find((r) => r.id === MID);
    expect(row?.state).toBe("downloading");
    expect(row?.bytesDone).toBe(4_500_000_000);
    expect(row?.etaS).toBe(120);
  });
});
