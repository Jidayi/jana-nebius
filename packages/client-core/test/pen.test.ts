// UXS-56 (D103): on a scripted turn the pen rests at the end of the line being written, reaches each cue's target before
// its ring appears, and an off-screen target leaves the pen at rest and is logged (VSL-45).
import { describe, expect, test } from "vitest";
import { CueSync, PEN_LEAD_MS, type CaptionWord, type PointerTarget } from "../src/index.js";

const LINE = `stp_${"7".repeat(26)}`;
const OTHER = `stp_${"8".repeat(26)}`;
const PART = `vis_${"9".repeat(26)}:force.weight`;
const GONE = `stp_${"6".repeat(26)}`;
const id = (t: PointerTarget | null) => t === null ? null : t.kind === "step" ? t.step_id : `${t.visual_id}:${t.part_id}`;

describe("UXS-56", () => {
  test("uxs56_pen_follows_cues", () => {
    const text = "We write the line then look at this one and at the weight and that one";
    const words: CaptionWord[] = [...text.matchAll(/\S+/g)].map((m, i) => ({ w: m[0], start_ms: 200 + i * 300 }));
    const at = (word: string) => text.indexOf(word);
    const onScreen = (t: PointerTarget) => id(t) !== GONE;
    const sync = new CueSync(600, () => undefined, onScreen);
    sync.caption("trn_1", text, words, [
      { char_offset: at("write"), target: LINE, action: "write", end_offset: at("line") + 4 },
      { char_offset: at("this"), target: OTHER },
      { char_offset: at("weight"), target: PART },
      { char_offset: at("that"), target: GONE },
    ], "measured");
    const arrivals = new Map<string, number>(), rings = new Map<string, number>();
    const quiet: { played: number; penAt: string | null }[] = [];
    for (let played = 0; played <= 7000; played += 10) {
      sync.progress(played, played);
      const { pen, pointer, writing } = sync.getState();
      const penAt = id(pen.target);
      if (penAt !== null && !arrivals.has(penAt)) arrivals.set(penAt, played);
      const ring = pointer === null ? null : id(pointer.target);
      if (ring !== null && !rings.has(ring)) rings.set(ring, played);
      if (writing !== null && pointer === null) quiet.push({ played, penAt });
    }
    // While the line is being written and nothing is pointed at, the pen rests at that line.
    // With no ring showing, the pen is at rest at the line being written, unless it has set off for the next target
    // (it leaves at most PEN_LEAD_MS before that target's ring).
    const resting = quiet.filter(({ played, penAt }) => !(penAt !== null && penAt !== LINE && rings.has(penAt) && rings.get(penAt)! - played <= PEN_LEAD_MS));
    expect(resting.length).toBeGreaterThan(0);
    expect(resting.every(({ penAt }) => penAt === LINE)).toBe(true);
    // The pen reaches each on-screen target before its ring appears.
    for (const target of [OTHER, PART]) {
      expect(arrivals.get(target), target).toBeDefined();
      expect(arrivals.get(target)!, target).toBeLessThan(rings.get(target)!);
    }
    // An off-screen target: the pen never heads for it, and the miss is logged by id.
    expect(arrivals.has(GONE)).toBe(false);
    expect(sync.penMisses).toEqual([GONE]);
  });
});
