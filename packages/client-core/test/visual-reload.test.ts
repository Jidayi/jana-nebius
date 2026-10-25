import { expect, test } from "vitest";
import { hydrate, type CoreSnapshot } from "../src/hydrate.js";
import { emptyStore } from "../src/store.js";
import { historyStore } from "../src/history.js";
import { OPENED } from "./parentcore.js";

test("snapshot hydration retains an annotation, pending placement and rough sketch", () => {
  const board = { board_id: "brd_1", part_id: "prt_1", problem: null, knowns: [], unknowns: [], conventions: [],
    steps: {}, order: [], awaiting: null, highlight: null,
    annotation: { annotation_id: "ann_1", mark: "circle" as const, target: { step_id: "stp_1", terms: "t1", visual_id: null, part_id: null }, to: null, note: null },
    manipulation: { step_id: "stp_2", visual_id: "vis_1", part_ids: ["sol.from"], prompt: "Match the point" } };
  const sketch = { sketch_id: "skt_1", status: "not_checked" as const };
  const snapshot: CoreSnapshot = {
    session: { session_id: "ses_1", title: "Synthetic", mode: "guided", subject: "physics", topic_id: null, created_ts: 1, updated_ts: 1, archived: false },
    cursor: { epoch: "qa", seq: 20 }, messages: [], visuals: {}, open_requests: [], active_turn: null,
    boards: { brd_1: board }, parts: { prt_1: { part_id: "prt_1", turn_id: null, kind: "visual", index: 0, status: "complete", text: "", sketch } },
  };
  const store = hydrate(emptyStore(), JSON.parse(JSON.stringify(snapshot)));
  expect(store.boards.brd_1?.annotation).toEqual(board.annotation);
  expect(store.boards.brd_1?.manipulation).toEqual(board.manipulation);
  expect(store.parts.prt_1?.sketch).toEqual(sketch);
});

test("history uses saved board metadata and the latest checked SQL step", () => {
  const opened = structuredClone(OPENED);
  const first = opened.boards[0]!;
  opened.parts.board = { part_id: "board", turn_id: opened.messages[1]!.turn_id, kind: "board", index: 2, status: "complete", text: "",
    boards: [{ board_id: first.board_id, part_id: "board", problem: { text: "Synthetic diagram", latex: null }, knowns: [], unknowns: [], conventions: [],
      steps: {}, order: [], awaiting: null, highlight: null,
      annotation: { annotation_id: "ann_1", mark: "circle", target: { step_id: first.steps[0]!.step_id, terms: null, visual_id: null, part_id: null }, to: null, note: null } }] };
  const store = historyStore(opened);
  expect(store.boards[first.board_id]?.problem?.text).toBe("Synthetic diagram");
  expect(store.boards[first.board_id]?.annotation?.mark).toBe("circle");
  expect(store.boards[first.board_id]?.steps[first.steps[0]!.step_id]?.latex).toBe(first.steps[0]!.latex);
});
