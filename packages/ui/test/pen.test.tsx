// UXS-56 (D103): with reduced motion the pen jumps to each target without travel; otherwise it travels; low power hides
// it; it is never announced (the ring and "Showing: …" carry the meaning).
import { cleanup, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, test } from "vitest";
import type { PenView } from "@jana/client-core";
import { Pen } from "../src/board/Pen.js";

afterEach(() => cleanup());

const STEP = `stp_${"3".repeat(26)}`;

function Board({ pen, reducedMotion, lowPower = false }: { pen: PenView; reducedMotion: boolean; lowPower?: boolean }) {
  const box = useRef<HTMLElement | null>(null);
  return (
    <section ref={box}>
      <ol><li data-step-id={STEP}><span className="board-math">x = 2</span></li></ol>
      <span data-part="force.weight">W</span>
      <Pen pen={pen} container={box} reducedMotion={reducedMotion} lowPower={lowPower} />
    </section>
  );
}

const pen = (target: PenView["target"]): PenView => ({ target, since_ms: 100 });
const marker = () => document.querySelector("[data-pen]") as HTMLElement | null;

describe("UXS-56", () => {
  test("uxs56_pen_reduced_motion_jumps", () => {
    const { rerender } = render(<Board pen={pen({ kind: "step", step_id: STEP })} reducedMotion />);
    expect(marker()?.getAttribute("data-pen-motion")).toBe("jump");
    expect(marker()?.style.transition).toBe("none");
    rerender(<Board pen={pen({ kind: "part", visual_id: `vis_${"1".repeat(26)}`, part_id: "force.weight" })} reducedMotion />);
    expect(marker()?.getAttribute("data-pen-target")).toBe('[data-part="force.weight"]');
    expect(marker()?.style.transition).toBe("none");
    // Without reduced motion it travels on its arc.
    rerender(<Board pen={pen({ kind: "step", step_id: STEP })} reducedMotion={false} />);
    expect(marker()?.getAttribute("data-pen-motion")).toBe("travel");
    expect(marker()?.style.transition).toContain("transform");
    // It is decoration only, and low-power mode hides it.
    expect(marker()?.getAttribute("aria-hidden")).toBe("true");
    rerender(<Board pen={pen({ kind: "step", step_id: STEP })} reducedMotion={false} lowPower />);
    expect(marker()).toBeNull();
    // A target that is not on screen: no pen is drawn there.
    rerender(<Board pen={pen({ kind: "step", step_id: `stp_${"9".repeat(26)}` })} reducedMotion={false} />);
    expect(marker()).toBeNull();
  });
});
