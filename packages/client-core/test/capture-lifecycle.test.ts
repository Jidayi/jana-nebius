import { expect, test } from "vitest";
import { typedCapture, reviseTypedCapture, confirmTypedCapture, cancelTypedCapture, assertConfirmed } from "../src/capture.js";

test("inp02_lifecycle_transitions: typed drafts keep identity until Send or cancellation", () => {
  const draft = typedCapture("", { sessionId: "ses_synthetic", purpose: "question", confirmed: false, now: 1000 });
  const revised = reviseTypedCapture(draft, "e\u0301\u202e x^2", { now: 2000, pasted: true });
  expect(revised.capture_id).toBe(draft.capture_id);
  expect(revised.created_at).toBe(1000);
  expect(revised.text).toBe("é x^2");
  expect(() => assertConfirmed(revised)).toThrow("capture_unconfirmed");
  const sent = confirmTypedCapture(revised, 3000);
  expect(sent.status).toBe("confirmed");
  expect(sent.confirmation.confirmed_at).toBe(3000);
  expect(sent.source).toBe("pasted_text");
  expect(() => assertConfirmed(sent)).not.toThrow();
  expect(() => reviseTypedCapture(sent, "changed")).toThrow("capture_terminal");
  const cancelled = cancelTypedCapture(revised, 3000);
  expect(cancelled.text).toBe("");
  expect(cancelled.status).toBe("cancelled");
  expect(() => confirmTypedCapture(cancelled)).toThrow("capture_terminal");
});

test("question selection preserves diagram values and accounting cells in editable confirmation text", async () => {
  const { captureRegionText } = await import("../src/capture.js");
  expect(captureRegionText({ text: "Find x", diagram_description: "Triangle sides 3 and 4", table: null })).toBe("Find x\nTriangle sides 3 and 4");
  expect(captureRegionText({ text: "Prepare the journal", table: { template: "journal", columns: ["Account", "Dr", "Cr"], rows: [["Cash", "100", ""], ["Sales", "", "100"]] } })).toContain("Cash | 100 | \nSales |  | 100");
});
