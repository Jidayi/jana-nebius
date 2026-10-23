import { describe, expect, it, vi } from "vitest";
import { Draft } from "../src/draft.js";
import { StudioError, type Command, type Opened } from "../src/model.js";
const opened: Opened = { pack: "pack.phy.o", table: "items", path: "item.yaml", revision: "one", record: { id: "itm.phy.o.motion.0001", stem: "original" } };
function setup() {
  let release!: (value: Opened) => void;
  const save = vi.fn((_request: Record<string, unknown>) => new Promise<Opened>((resolve) => { release = resolve; }));
  const command = (async (request: Record<string, unknown>) => request.op === "validate" ? { ok: true, problems: [] } : save(request)) as Command;
  return { command, save, release: (value: Opened) => release(value) };
}
describe("working-copy draft lifecycle", () => {
  it("drains edits typed during a save before permitting navigation, using the returned revision", async () => {
    const s = setup(), draft = new Draft(opened, s.command, "lead");
    draft.change(JSON.stringify({ ...opened.record, stem: "first edit" }));
    const first = draft.flush();
    draft.change(JSON.stringify({ ...opened.record, stem: "second edit" }));
    s.release({ ...opened, revision: "two", record: { ...opened.record, stem: "first edit", version: "0.1.1" } });
    await vi.waitFor(() => expect(s.save).toHaveBeenCalledTimes(2));
    expect(s.save.mock.calls[1]?.[0]).toMatchObject({ revision: "two", record: { stem: "second edit", version: "0.1.1" } });
    expect(draft.getState().dirty).toBe(true);
    expect(JSON.parse(draft.getState().text)).toMatchObject({ stem: "second edit", version: "0.1.1" });
    s.release({ ...opened, revision: "three", record: { ...opened.record, stem: "second edit" } });
    expect(await first).toBe(true); expect(draft.getState().dirty).toBe(false); draft.close();
  });
  it("keeps incomplete JSON typed during a save and prevents navigation", async () => {
    const s = setup(), draft = new Draft(opened, s.command, "lead");
    draft.change(JSON.stringify({ ...opened.record, stem: "first edit" }));
    const leaving = draft.flush(); draft.change('{"unfinished":');
    s.release({ ...opened, revision: "two" });
    expect(await leaving).toBe(false); expect(draft.getState().text).toBe('{"unfinished":');
    expect(draft.getState().dirty).toBe(true); draft.close();
  });
  it("retains the raw text and blocks navigation when JSON cannot be saved", async () => {
    const s = setup(), draft = new Draft(opened, s.command, "lead");
    draft.change('{"unfinished":');
    expect(await draft.flush()).toBe(false); expect(s.save).not.toHaveBeenCalled();
    expect(draft.getState().text).toBe('{"unfinished":'); expect(draft.getState().dirty).toBe(true); draft.close();
  });
  it("never retries a conflicting revision automatically or discards the draft", async () => {
    const save = vi.fn(async () => { throw new StudioError("conflict", "Changed on disk"); });
    const command = (async (request) => request.op === "validate" ? { ok: true, problems: [] } : save()) as Command;
    const draft = new Draft(opened, command, "lead"); draft.change(JSON.stringify({ ...opened.record, stem: "retained" }));
    expect(await draft.flush()).toBe(false); expect(await draft.flush()).toBe(false);
    expect(save).toHaveBeenCalledOnce(); expect(draft.getState().conflict).toBe(true);
    expect(draft.getState().text).toContain("retained"); draft.close();
  });
  it("treats a new record as an unsaved draft even before the first edit", async () => {
    const s = setup(), draft = new Draft({ ...opened, new: true }, s.command, "lead");
    expect(draft.getState().dirty).toBe(true);
    const saving = draft.flush(); s.release(opened); expect(await saving).toBe(true); draft.close();
  });
  it("ignores old validation replies after typing newer text", async () => {
    const pending: ((value: unknown) => void)[] = [];
    const command = (async () => new Promise<unknown>((resolve) => pending.push(resolve))) as Command;
    const draft = new Draft(opened, command, "lead");
    draft.change(JSON.stringify({ ...opened.record, stem: "new" })); draft.check();
    pending[1]?.({ ok: false, problems: ["new error"] }); await Promise.resolve(); await Promise.resolve();
    pending[0]?.({ ok: true, problems: [] }); await Promise.resolve(); await Promise.resolve();
    expect(draft.getState().report?.problems).toEqual(["new error"]); draft.close();
  });
});

it("allows a creation identity only before the first save and binds later saves to it", async () => {
  const s = setup(), draft = new Draft({ ...opened, new: true }, s.command, "lead");
  expect(draft.canEditIdentity()).toBe(true);
  const created = { ...opened, record: { ...opened.record, id: "itm.phy.o.motion.0099" }, revision: "created" };
  draft.change(JSON.stringify(created.record)); const saving = draft.flush();
  expect(draft.canEditIdentity()).toBe(false); expect(s.save.mock.calls[0]?.[0].id).toBe(created.record.id);
  s.release(created); expect(await saving).toBe(true); expect(draft.canEditIdentity()).toBe(false);
  draft.change(JSON.stringify({ ...created.record, stem: "edited" })); const second = draft.flush();
  expect(s.save.mock.calls[1]?.[0].id).toBe(created.record.id); s.release(created); expect(await second).toBe(true); draft.close();
});
