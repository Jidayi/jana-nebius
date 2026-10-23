import { test } from "node:test";
import assert from "node:assert/strict";
import Color from "colorjs.io";
import { readFile } from "node:fs/promises";
import { TOKENS } from "../../packages/ui/src/generated/tokens.ts";
import { simulate, colourVisionReport } from "./colour-vision.mjs";
test("CIEDE2000 uses the published Sharma reference pair", () => {
  const a = new Color("lab", [50, 2.6772, -79.7751]), b = new Color("lab", [50, 0, -82.7485]);
  assert.ok(Math.abs(a.deltaE(b, "2000") - 2.0425) < .0001);
});
test("simulation preserves black and white and duplicate role colours cannot pass", () => {
  for (const mode of ["protanopia", "deuteranopia", "tritanopia"]) {
    assert.deepEqual(simulate("#000000", mode).coords, [0, 0, 0]);
    assert.ok(simulate("#ffffff", mode).coords.every((c) => Math.abs(c - 1) < .00001));
  }
  const roles = ["verified", "hint", "misconception", "highlight", "series-1", "series-2", "series-3", "series-4"];
  const report = colourVisionReport({ aliases: {}, color: Object.fromEntries(roles.map((r) => [r, { light: "#123456", dark: "#123456" }])) });
  assert.equal(report.rows.length, 168);
  assert.equal(report.failures.length, 168);
  assert.ok(report.failures.every((r) => r.delta_e_2000 === 0));
});
test("loc19_cvd_distinguishable: the canonical palette meets contrast and all 168 CVD comparisons", async () => {
  const proposal = JSON.parse(await readFile(new URL("../governance/app-completion-palette-proposal.json", import.meta.url), "utf8"));
  const tokens = TOKENS;
  for (const [role, value] of Object.entries(proposal.proposed_colour_roles)) assert.deepEqual(tokens.color[role], value);
  for (const role of proposal.remove_aliases) assert.equal(tokens.aliases[role], undefined);
  for (const colour of Object.values(tokens.color)) {
    if (!colour.contrast) continue;
    for (const theme of ["light", "dark"]) for (const surface of colour.contrast.against) {
      let role = surface;
      while (tokens.aliases[role]) role = tokens.aliases[role];
      assert.ok(new Color(colour[theme]).contrast(new Color(tokens.color[role][theme]), "WCAG21") >= colour.contrast.required);
    }
  }
  assert.equal(colourVisionReport(tokens).failures.length, 0);
});
