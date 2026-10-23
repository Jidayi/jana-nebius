import { expect, test } from "vitest";
import { SessionController, StoreHolder } from "../src/session.js";
import { ulid } from "../src/ids.js";

test("a temporarily unavailable checker keeps the line and allows the same command to be retried", async () => {
  const keys: string[] = [];
  const holder = new StoreHolder();
  const sessionId = `ses_${ulid()}`;
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, sessionId, {
    fetch: async (_url, init) => {
      keys.push(new Headers(init?.headers).get("idempotency-key")!);
      return keys.length === 1 ? new Response(JSON.stringify({ error: { code: "worker_unavailable", retryable: true,
        details: { hint_key: "unbalanced_bracket", position: 2 } } }), { status: 503 }) :
        new Response(JSON.stringify({ turn_id: `trn_${ulid()}`, message_id: `msg_${ulid()}` }), { status: 202 });
    },
  });
  try {
    const key = session.sendBoardLine(`stp_${ulid()}`, "x=2");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(holder.getState().messages[key]?.state).toBe("failed");
    expect(holder.getState().messages[key]?.content[0]).toMatchObject({ type: "board_line", latex: "x=2" });
    expect(holder.getState().messages[key]?.error_details?.position).toBe(2);
    session.retry(key);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(keys).toEqual([key, key]);
  } finally { session.close(); }
});

test("correcting a refused draft retires its old retry and keeps the correction retryable", async () => {
  const keys: string[] = [];
  const holder = new StoreHolder();
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, `ses_${ulid()}`, {
    fetch: async (_url, init) => {
      keys.push(new Headers(init?.headers).get("idempotency-key")!);
      return new Response(JSON.stringify({ error: { code: "parse_error", retryable: true } }), { status: 422 });
    },
  });
  try {
    const refused = session.sendWorking("x=2");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(holder.getState().messages[refused]?.state).toBe("failed");
    session.discardFailed(refused);
    session.retry(refused);
    const correction = session.sendWorking("x=3");
    await new Promise((resolve) => setTimeout(resolve, 0));
    session.retry(correction);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(keys).toEqual([refused, correction, correction]);
  } finally { session.close(); }
});
