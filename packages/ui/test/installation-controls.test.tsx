import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LocaleProvider } from "../src/i18n.js";
import { ModelManager } from "../src/settings/ModelManager.js";

afterEach(cleanup);

test("download controls keep mobile-data permission separate from the speed cap and can cancel", () => {
  const onLimits = vi.fn();
  const onCancel = vi.fn();
  render(<LocaleProvider locale="en"><ModelManager view={{ kind: "ready", shortfalls: [], downloadsOff: false,
    reasonKey: null, freeBytes: null, rows: [{ id: "mp.synthetic.8b.q4.low", sizeBytes: 2000, hardwareClass: "low",
      recommended: false, state: "paused", bytesDone: 1000, etaS: null, licence: "Apache-2.0", downloadId: "dl_synthetic",
      limits: { bandwidth_bytes_per_s: 1024 ** 2, allow_metered: false }, meteredPaused: true }] }}
    actions={{ onDownload: vi.fn(), onPause: vi.fn(), onResume: vi.fn(), onDelete: vi.fn(), onImport: vi.fn(),
      onFreeSpace: vi.fn(), onCancel, onLimits }} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("checkbox", { name: "Allow this download on mobile data" }));
  expect(onLimits).toHaveBeenLastCalledWith("dl_synthetic", { bandwidth_bytes_per_s: 1024 ** 2, allow_metered: true });
  fireEvent.change(screen.getByRole("combobox", { name: "Download speed limit" }), { target: { value: String(256 * 1024) } });
  expect(onLimits).toHaveBeenLastCalledWith("dl_synthetic", { bandwidth_bytes_per_s: 256 * 1024, allow_metered: false });
  fireEvent.click(screen.getByRole("button", { name: "Cancel download" }));
  expect(onCancel).toHaveBeenCalledWith("dl_synthetic");
  expect(screen.getByText("Paused on mobile data")).toBeTruthy();
});
