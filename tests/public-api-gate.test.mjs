import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../site/public-api-gate.js", import.meta.url), "utf8");
const context = {};
vm.runInNewContext(`${source}\nthis.gate = handler;`, context);

const request = (method, uri) => ({ request: { method, uri } });

test("public API gate allows only the three approved operations", () => {
  for (const [method, uri] of [
    ["GET", "/api/config"],
    ["POST", "/api/chat"],
    ["POST", "/api/reset"],
  ]) {
    assert.deepEqual(context.gate(request(method, uri)), { method, uri });
  }

  for (const [method, uri] of [
    ["POST", "/api/config"],
    ["GET", "/api/chat"],
    ["DELETE", "/api/reset"],
    ["POST", "/api/unknown"],
  ]) {
    const response = context.gate(request(method, uri));
    assert.equal(response.statusCode, 404);
    assert.equal(response.headers["content-type"].value, "application/json");
    assert.deepEqual(JSON.parse(response.body.data), { error: { code: "not_found" } });
  }
});
