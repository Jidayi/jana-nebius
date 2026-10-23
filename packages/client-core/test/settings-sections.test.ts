// UXS-46: the Settings sections as the core lists them (`GET /v1/settings/sections`), checked against the command
// contract; a reply that does not hold is refused, and a core without the route gives the stage 2 sections.
import { describe, expect, test } from "vitest";
import { CommandClient, SettingsSections, STAGE_2_SECTIONS } from "../src/index.js";

function serving(status: number, body: unknown): CommandClient {
  return new CommandClient({
    endpoint: async () => ({ baseUrl: "http://core.test", token: "t" }),
    fetch: async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  });
}

const section = (id: string) => ({ id, gate: "open", offline: true, states: ["ready", "empty", "error"] });

describe("UXS-46", () => {
  test("test_uxs46_sections_read_in_the_cores_order", async () => {
    const ids = [...STAGE_2_SECTIONS, "parent_summary", "alerts", "voice"];
    expect(await new SettingsSections(serving(200, { stage: "S3", sections: ids.map(section) })).read()).toEqual(ids);
    // A section that is not open, or not offline, is not a section the contract allows: the reply is refused.
    const gated = { stage: "S2", sections: [{ ...section("profiles"), gate: "pin" }] };
    await expect(new SettingsSections(serving(200, gated)).read()).rejects.toMatchObject({ code: "invalid_reply" });
    // A core from before the route: the stage 2 sections, in the table's order.
    expect(await new SettingsSections(serving(404, { error: { code: "not_found", message: "no route" } })).read()).toEqual([...STAGE_2_SECTIONS]);
  });
});
