import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ProfileController, StoreHolder } from "@jana/client-core";
import { FakeProfileCore } from "../../client-core/test/profilecore.js";
import { HealthPanel } from "../src/settings/HealthPanel.js";
import { LocaleProvider } from "../src/i18n.js";
afterEach(cleanup);
test.each(["light", "dark"])("inp33_trace_fields_no_content: local aggregate health copy in %s", async (theme) => {
  const core = new FakeProfileCore();
  core.health.perception = [{ hardware_class: "mid", captures: 8, confirmed: 5, edited: 2, unreadable: 1 }];
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  const { container } = render(<div data-theme={theme}><LocaleProvider locale="en"><HealthPanel profiles={profiles} /></LocaleProvider></div>);
  fireEvent.click(screen.getByRole("button", { name: "How the tutor is running" }));
  await screen.findByText("Photo reading on this computer");
  expect(container.textContent).toContain("mid: 8 photos; 5 confirmed, 2 edited, 1 unreadable.");
  expect(core.log.some((r) => r.path === "/v1/health")).toBe(true);
  expect(core.log.every((r) => r.method === "GET")).toBe(true);
});
