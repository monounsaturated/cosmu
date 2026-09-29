// Unit test for the operator session token (HMAC mint/verify + expiry). Web Crypto is available in the Node
// test runtime, so this runs under `node --test --experimental-strip-types operator-session.test.ts` and
// typechecks under `pnpm typecheck`.

import { strict as assert } from "node:assert";
import { test } from "node:test";
import { mintOperatorToken, verifyOperatorToken } from "./operator-session.ts";

const SECRET = "a-long-random-session-secret-value";

test("mint then verify round-trips", async () => {
  const token = await mintOperatorToken(SECRET, 60);
  assert.ok(token, "token minted");
  assert.equal(await verifyOperatorToken(token, SECRET), true);
});

test("no secret → cannot mint and never verifies (fail closed)", async () => {
  assert.equal(await mintOperatorToken(undefined, 60), null);
  const token = await mintOperatorToken(SECRET, 60);
  assert.equal(await verifyOperatorToken(token, undefined), false);
});

test("expired token is rejected", async () => {
  const nowSec = 1_000_000;
  const token = await mintOperatorToken(SECRET, 30, nowSec);
  // verify AFTER expiry
  assert.equal(await verifyOperatorToken(token, SECRET, nowSec + 31), false);
  // verify BEFORE expiry
  assert.equal(await verifyOperatorToken(token, SECRET, nowSec + 10), true);
});

test("tampered token / wrong secret is rejected", async () => {
  const token = await mintOperatorToken(SECRET, 60);
  assert.ok(token);
  assert.equal(await verifyOperatorToken(token, "different-secret"), false);
  // tamper the exp (bump it) → MAC no longer matches
  const [v, exp, sig] = (token as string).split(".");
  const tampered = `${v}.${Number(exp) + 10000}.${sig}`;
  assert.equal(await verifyOperatorToken(tampered, SECRET), false);
  // garbage / wrong-arity tokens
  assert.equal(await verifyOperatorToken("not.a.token.at.all", SECRET), false);
  assert.equal(await verifyOperatorToken("", SECRET), false);
});
