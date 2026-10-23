// Recorded core streams (evals/recordings, written by `python -m jana_tools recordings --write`).
import fs from "node:fs";
import path from "node:path";
import type { ContentBlock } from "@jana/contracts-ts";
import type { CoreSnapshot } from "../src/hydrate.js";
import type { Envelope } from "../src/queue.js";

export interface Recording {
  name: string;
  session_id: string;
  sends: { after_seq: number; body: { client_message_id: string; intent: string; content: ContentBlock[] } }[];
  frames: Envelope[];
  snapshots: CoreSnapshot[];
}

const dir = path.resolve(import.meta.dirname, "../../../evals/recordings");

export function recordings(): Recording[] {
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) as Recording);
}
