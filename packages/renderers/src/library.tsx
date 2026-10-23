// library_diagram (VSL-03, VSL-22, VSL-26): a vetted drawing from the diagram library, with tappable parts and an
// optional process sequence. The drawing is the entry's sanitised SVG carried by the resolution; it is parsed and
// checked again here (VSL-23) and drawn as elements, never injected. Parts follow the entry's tab order (LOC-15),
// labels obey the label mode (VSL-11: hidden removes them, quiz numbers blanks), a sequence step shows its pre-drawn
// arrows, and a highlighted part is drawn with the ring stroke and an underlined label.
import { createElement, type ReactElement, type ReactNode } from "react";
import { define } from "./define.js";
import { INK, MUTED, PAPER, RING, RING_STROKE, STRONG, WordsFallback, computed, described, highlighted, partName, partNameRef, type Scene } from "./kit.js";
import { SvgRefused, parseSvg, reactProps, svgProblems, type SvgNode } from "./library_svg.js";

interface EntryPart {
  id: string;
  name: string;
  initially_hidden?: boolean;
}

interface LibraryComputed {
  svg?: string;
  entry?: { parts?: EntryPart[]; sequences?: { id: string; steps: { highlight: string[]; arrows?: string[] }[] }[]; regions?: { id: string; viewbox: number[] }[] };
}

function drawNode(n: SvgNode, s: Scene, key: string, ctx: { hl: boolean; arrows: Set<string>; hidden: Set<string> }): ReactNode {
  const attrs = reactProps(n.attrs);
  const part = n.attrs["data-part"];
  const arrow = n.attrs["data-arrow"];
  const labelFor = n.attrs["data-label-for"];
  if (arrow !== undefined && !ctx.arrows.has(arrow)) return null;
  if (part !== undefined && ctx.hidden.has(part)) return null;
  if (n.tag === "title" || n.tag === "desc") return null;
  if (labelFor !== undefined) {
    if (s.labels === "hidden") return null;
    if (s.labels === "quiz") {
      const index = s.order.get(labelFor) ?? 0;
      const x = Number(n.attrs.x ?? 0);
      const y = Number(n.attrs.y ?? 0);
      const size = Number(n.attrs["font-size"] ?? 13) * s.scale;
      return (
        <g key={key} data-blank-for={labelFor}>
          <rect x={x} y={y - size} width={size * 2} height={size * 1.3} fill={PAPER} stroke={STRONG} strokeWidth={1} strokeDasharray="3 2" />
          <text x={x + size} y={y} fontSize={size} textAnchor="middle" fill={MUTED}>{index}</text>
        </g>
      );
    }
  }
  const hl = ctx.hl || (part !== undefined && highlighted(s, part));
  if (attrs.fontSize !== undefined) attrs.fontSize = String(Number(attrs.fontSize) * s.scale);
  // A content colour keeps its line-strong outline even when highlighted (DSN-18); the label still shows the highlight.
  if (hl && n.tag !== "text" && n.tag !== "tspan" && attrs.stroke !== undefined && attrs.stroke !== "none" && n.attrs["data-content-colour"] === undefined) {
    attrs.stroke = RING;
    attrs.strokeWidth = String(Math.max(RING_STROKE, Number(attrs.strokeWidth ?? 1.5)));
  }
  if (hl && n.tag === "text" && labelFor !== undefined) {
    attrs.textDecoration = "underline";
    attrs.fontWeight = "600";
  }
  const children = n.children.map((c, i) => (typeof c === "string" ? c : drawNode(c, s, `${key}.${i}`, { ...ctx, hl })));
  if (part !== undefined) {
    const extra = {
      ref: partNameRef(s, part), tabIndex: 0, role: "button", "aria-label": partName(s, part), "data-highlighted": highlighted(s, part) ? "true" : undefined,
      "data-pointed": s.focus.has(part) ? "true" : undefined, onClick: () => s.activate(part),
      onKeyDown: (e: { key: string; preventDefault(): void }) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          s.activate(part);
        }
      },
    };
    return createElement(n.tag, { key, ...attrs, ...extra }, ...children);
  }
  return createElement(n.tag, { key, ...attrs }, ...children);
}

function drawLibrary(s: Scene): ReactElement {
  const c = computed<LibraryComputed>(s.spec);
  if (c.svg === undefined) return <WordsFallback spec={s.spec} reason="text_only" />;
  let root: SvgNode;
  try {
    root = parseSvg(c.svg);
  } catch (error) {
    if (error instanceof SvgRefused) return <WordsFallback spec={s.spec} reason="refused" />;
    throw error;
  }
  if (svgProblems(root).length > 0) return <WordsFallback spec={s.spec} reason="refused" />;
  const p = s.spec.params as { sequence?: string; region?: string };
  const sequence = c.entry?.sequences?.find((q) => q.id === p.sequence);
  const step = Math.min((sequence?.steps.length ?? 0) - 1, s.step);
  const arrows = new Set(sequence !== undefined && step >= 0 ? (sequence.steps[step]?.arrows ?? []) : []);
  const hidden = new Set(s.state.hidden);
  for (const part of c.entry?.parts ?? []) if (part.initially_hidden === true && !s.state.revealed.has(part.id)) hidden.add(part.id);
  const region = c.entry?.regions?.find((r) => r.id === p.region);
  const viewBox = region !== undefined ? region.viewbox.join(" ") : (root.attrs.viewBox ?? "0 0 480 320");
  const children = root.children.map((child, i) => (typeof child === "string" ? null : drawNode(child, s, `n${i}`, { hl: false, arrows, hidden })));
  return (
    <svg viewBox={viewBox} role="group" aria-label={described(s)} className="w-full max-w-xl" data-kind={s.spec.type} data-visual-id={s.spec.visual_id} data-ref={s.spec.ref} stroke={undefined} color={INK}>
      {children}
    </svg>
  );
}

export const libraryDiagram = define({ kind: "library_diagram", schema: "visuals/kinds/library_diagram", labelModes: ["shown", "hidden", "quiz"], library: true, draw: drawLibrary });
