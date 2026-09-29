// Unit test for the web half of the two-tier money-path auth. Dependency-free: imports ONLY the pure
// lib/money-routes helpers (no next/server), so it typechecks under `pnpm typecheck` and runs under
// `node --test --experimental-strip-types money-routes.test.ts` with nothing installed.
//
// Proves: (1) every money route matches incl. normalization-evasion; reads/safety don't; (2) the dark-launch
// invariant — classifyEngineRequest is a PASS-THROUGH when the flag is unset (no behavior change on deploy).

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  classifyEngineRequest,
  isAuthEnforced,
  isMoneyMutation,
  isSameOrigin,
  MONEY_MUTATION_MATCHERS,
  normalizeEnginePath,
} from "./money-routes.ts";

test("every money-mutation route is matched (POST)", () => {
  for (const p of MONEY_MUTATION_MATCHERS) {
    assert.equal(isMoneyMutation("POST", p), true, `expected money mutation: ${p}`);
  }
  // spot-check the named critical set explicitly
  for (const p of ["/toggle/live", "/live/launch", "/live/defund", "/live/liquidate", "/ops/breaker/rearm"]) {
    assert.equal(isMoneyMutation("POST", p), true, p);
  }
});

test("reads and reduce-only safety routes are NOT money mutations", () => {
  assert.equal(isMoneyMutation("GET", "/toggle/live"), false); // GET on a money path
  assert.equal(isMoneyMutation("POST", "/ops/killswitch"), false); // reduce-only safety exit
  assert.equal(isMoneyMutation("POST", "/live/orders/abc/cancel"), false); // reduce-only cancel
  assert.equal(isMoneyMutation("POST", "/overview"), false); // arbitrary read-ish route
  assert.equal(isMoneyMutation("GET", "/live/venues"), false);
});

test("normalization defeats evasion (trailing slash, //, dots, case, backslash, %-encoding)", () => {
  const evils = [
    "/toggle/live/",
    "//toggle//live",
    "/toggle/./live",
    "/live/../toggle/live",
    "/TOGGLE/LIVE",
    "\\toggle\\live",
    "/toggle/%6cive", // %6c → 'l'
    "/%2e/toggle/live", // %2e → '.'
    "/api/engine/toggle/live", // proxy prefix stripped
    "/toggle/live?x=1", // query stripped
  ];
  for (const e of evils) {
    assert.equal(normalizeEnginePath(e), "/toggle/live", `normalize ${e}`);
    assert.equal(isMoneyMutation("POST", e), true, `money mutation ${e}`);
  }
});

test("isAuthEnforced is OFF by default and for falsey values", () => {
  for (const v of [undefined, null, "", "false", "0", "off", "no", "  "]) {
    assert.equal(isAuthEnforced(v), false, `should be off: ${JSON.stringify(v)}`);
  }
  for (const v of ["1", "true", "TRUE", "yes", "on", " true "]) {
    assert.equal(isAuthEnforced(v), true, `should be on: ${JSON.stringify(v)}`);
  }
});

test("DARK LAUNCH: middleware verdict is PASS when the flag is unset", () => {
  // The load-bearing invariant: with enforcement off, EVERY request (even a money mutation with no session)
  // passes through untouched — identical to no middleware at all.
  const moneyReq = classifyEngineRequest({
    enforced: false,
    method: "POST",
    enginePath: "/api/engine/live/launch",
    self: "https://app.example",
    origin: null,
    referer: null,
  });
  assert.deepEqual(moneyReq, { kind: "pass" });

  const readReq = classifyEngineRequest({
    enforced: false,
    method: "GET",
    enginePath: "/api/engine/overview",
    self: "https://app.example",
    origin: "https://evil.example",
    referer: null,
  });
  assert.deepEqual(readReq, { kind: "pass" });
});

test("ENFORCED: money mutation needs a session; cross-origin read is blocked; same-origin read passes", () => {
  const self = "https://app.example";
  assert.deepEqual(
    classifyEngineRequest({ enforced: true, method: "POST", enginePath: "/api/engine/toggle/live", self, origin: self, referer: null }),
    { kind: "need-session" },
  );
  assert.deepEqual(
    classifyEngineRequest({ enforced: true, method: "GET", enginePath: "/api/engine/overview", self, origin: "https://evil.example", referer: null }),
    { kind: "cross-origin" },
  );
  assert.deepEqual(
    classifyEngineRequest({ enforced: true, method: "GET", enginePath: "/api/engine/overview", self, origin: self, referer: null }),
    { kind: "pass" },
  );
  // no Origin/Referer at all → reads still pass (server-to-server / same-origin top-level GET)
  assert.deepEqual(
    classifyEngineRequest({ enforced: true, method: "GET", enginePath: "/api/engine/overview", self, origin: null, referer: null }),
    { kind: "pass" },
  );
});

test("isSameOrigin matches origin from Origin or Referer, rejects cross and malformed", () => {
  const self = "https://app.example";
  assert.equal(isSameOrigin(self, self, null), true);
  assert.equal(isSameOrigin(self, null, "https://app.example/some/page"), true);
  assert.equal(isSameOrigin(self, "https://evil.example", null), false);
  assert.equal(isSameOrigin(self, "not a url", null), false);
  assert.equal(isSameOrigin(self, null, null), true); // no signal → allow (mutations still gated by cookie)
});
