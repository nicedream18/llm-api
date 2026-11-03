import assert from "node:assert/strict";
import test from "node:test";

import { quotaDisplayState } from "./quotaDisplay.ts";

test("converts used quota into the remaining balance and matching tone", () => {
  assert.deepEqual(quotaDisplayState(25), { remaining: 75, tone: "success" });
  assert.deepEqual(quotaDisplayState(73), { remaining: 27, tone: "warning" });
  assert.deepEqual(quotaDisplayState(100), { remaining: 0, tone: "destructive" });
});

test("clamps out-of-range used quota before calculating the balance", () => {
  assert.deepEqual(quotaDisplayState(-20), { remaining: 100, tone: "success" });
  assert.deepEqual(quotaDisplayState(150), { remaining: 0, tone: "destructive" });
});

test("keeps the remaining balance unknown when used quota is absent", () => {
  assert.deepEqual(quotaDisplayState(null), { remaining: null, tone: "unknown" });
});
