import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const routing = /** @type {{handler(event: {request: {uri: string}, response?: {statusCode: number, headers: Record<string, {value: string}>}}): {uri?: string, headers?: Record<string, {value: string}>}}} */ ({});
vm.runInNewContext(await readFile(new URL("../agent/public-report-routes.js", import.meta.url), "utf8"), routing);

test("eval aliases remain usable across release changes without browser caching", () => {
  for (const uri of ["/assets/evals.mjs", "/assets/evals.css"]) {
    const response = {statusCode: 200, headers: {"cache-control": {value: "public, max-age=31536000, immutable"}}};
    assert.equal(routing.handler({request: {uri}, response}), response);
    assert.equal(response.headers["cache-control"].value, "no-store");
  }
  const response = {statusCode: 200, headers: {"cache-control": {value: "immutable"}}};
  assert.equal(routing.handler({request: {uri: "/releases/old/assets/evals.mjs"}, response}), response);
  assert.equal(response.headers["cache-control"].value, "immutable");
  assert.equal(routing.handler({request: {uri: "/eval-dashboard"}}).uri, "/evals.html");
  assert.equal(routing.handler({request: {uri: "/eval-dashboard/"}}).uri, "/evals.html");
});
