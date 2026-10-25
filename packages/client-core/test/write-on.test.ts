// UXS-55 (D103): over recorded voice turns, a line's last glyph finishes revealing within 150 ms of the end of the last
// spoken word that cites it, from the heard playback position (VOC-10, VOC-51).
import { describe, expect, test } from "vitest";
import { CueSync, type CaptionWord } from "../src/index.js";

const STEP = `stp_${"7".repeat(26)}`;

/** A recorded turn: its text, each word's start and end as heard, and the write cue's word range. */
interface Recorded { text: string; ends: number[]; starts: number[]; from: number; to: number }

function recorded(seed: number): Recorded {
  const words = ["So", "we", "subtract", "three", "from", "both", "sides", "and", "that", "gives", "two", "x", "equals", "ten", "which", "we", "divide", "next"];
  const count = 8 + (seed % 10);
  const used = words.slice(0, count);
  let t = 120 + (seed * 37) % 200;
  const starts: number[] = [], ends: number[] = [];
  for (const [i, w] of used.entries()) {
    starts.push(t);
    const length = 140 + ((seed * 31 + i * 17) % 160) + w.length * 12;
    ends.push(t + length);
    t += length + 40 + ((seed + i) % 4) * 25; // the pause before the next word
  }
  const from = 1 + (seed % 3);
  const to = Math.min(count - 1, from + 2 + (seed % 5)); // the last word that cites the line
  return { text: used.join(" "), starts, ends, from, to };
}

function offsets(text: string): { start: number; end: number }[] {
  return [...text.matchAll(/\S+/g)].map((m) => ({ start: m.index ?? 0, end: (m.index ?? 0) + m[0].length }));
}

describe("UXS-55", () => {
  test("uxs55_write_on_synced_to_speech", () => {
    for (let seed = 0; seed < 40; seed += 1) {
      const turn = recorded(seed);
      const spans = offsets(turn.text);
      const words: CaptionWord[] = spans.map((_, i) => ({ w: turn.text.slice(spans[i]!.start, spans[i]!.end), start_ms: turn.starts[i]! }));
      const sync = new CueSync(1500);
      sync.caption("trn_1", turn.text, words, [{ char_offset: spans[turn.from]!.start, target: STEP, action: "write", end_offset: spans[turn.to]!.end }], "measured");
      let finished: number | null = null;
      for (let played = 0; played <= turn.ends.at(-1)! + 800; played += 10) {
        sync.progress(played, played);
        const writing = sync.getState().writing;
        if (finished === null && writing?.step_id === STEP && writing.progress >= 1) finished = played;
      }
      expect(finished, `seed ${seed}`).not.toBeNull();
      // The last glyph lands within 150 ms of the end of the last word that cites the line.
      expect(Math.abs(finished! - turn.ends[turn.to]!), `seed ${seed}`).toBeLessThanOrEqual(150);
      // And the reveal never runs ahead of the first citing word.
      expect(sync.records.find((r) => r.action === "write")?.word_ms).toBe(turn.starts[turn.from]);
    }
  });
});
