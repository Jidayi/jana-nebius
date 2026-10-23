// OBS-20 and PRV-09: what Settings lists of a usage report is read from the published report schema as the core serves
// it (`GET /v1/telemetry/schema`, here the bundled `trace/telemetry` contract): every top-level field with its fixed
// values, every measurement and each breakdown; a reply that is not that schema is refused.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { CommandClient, readTelemetrySchema } from "../src/index.js";

const SCHEMA = path.resolve(import.meta.dirname, "../../../services/agent-core/agent_core/contracts/schemas/trace/telemetry.schema.json");

function serving(body: unknown): CommandClient {
  return new CommandClient({
    endpoint: async () => ({ baseUrl: "http://core.test", token: "t" }),
    fetch: async () => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }),
  });
}

describe("OBS-20", () => {
  test("test_obs20_report_schema_summary", async () => {
    const schema = JSON.parse(fs.readFileSync(SCHEMA, "utf8")) as { properties: Record<string, unknown>; $defs: { metrics: { properties: Record<string, unknown> } } };
    const summary = await readTelemetrySchema(serving(schema));
    expect(summary.fields.map((f) => f.name)).toEqual(Object.keys(schema.properties).filter((k) => !["metrics", "series", "labels"].includes(k)));
    expect(summary.fields.find((f) => f.name === "channel")?.values).toEqual(["dev", "pilot", "stable"]);
    expect(summary.fields.find((f) => f.name === "report_id")?.values).toBeNull();
    expect(summary.metrics).toEqual(Object.keys(schema.$defs.metrics.properties));
    expect(summary.breakdowns.length).toBeGreaterThan(0);
    expect(summary.breakdowns.every((b) => b.values !== null && b.values.length > 0)).toBe(true);
    expect(summary.maxDays).toBe(14);
    await expect(readTelemetrySchema(serving({ title: "not a schema" }))).rejects.toMatchObject({ code: "invalid_reply" });
  });
});
