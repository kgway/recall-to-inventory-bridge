// SPDX-License-Identifier: MPL-2.0
const {test} = require("node:test");
const assert = require("node:assert/strict");
const {RetailerRequest} = require("../web/retailer-request.js");

function storage() {
  const data = new Map();
  return {getItem: k => data.get(k) || null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k)};
}
const receipt = request => ({...request, allowed: true, blocked: [], replayed: false});

test("lost acknowledgement, reload and retry consume stock only once", async () => {
  const saved = storage();
  let ids = 0, stock = 5;
  let client = new RetailerRequest(saved, () => "order-" + ++ids);
  const ledger = new Map();
  const server = async request => {
    if (!ledger.has(request.idempotency_key)) {
      stock--;
      ledger.set(request.idempotency_key, receipt(request));
    }
    return {...ledger.get(request.idempotency_key), replayed: true};
  };
  client.begin("synthetic-lot", "sale");
  await assert.rejects(client.send(async request => {await server(request); throw Error("response lost");}), /response lost/);
  assert.equal(stock, 4);
  client = new RetailerRequest(saved, () => "order-" + ++ids);
  assert.throws(() => client.begin("another-lot", "shipment"), /pending/);
  assert.equal((await client.send(server)).replayed, true);
  assert.equal(stock, 4);
  assert.equal(ids, 1);
  assert.equal(client.pending, null);
  assert.equal(new RetailerRequest(saved, () => "unused").pending, null);
});

test("a second click cannot dispatch while the first request is in flight", async () => {
  const client = new RetailerRequest(storage(), () => "same-order");
  client.begin("lot", "shipment");
  let finish, dispatched = 0;
  const first = client.send(request => {dispatched++; return new Promise(resolve => {finish = () => resolve(receipt(request));});});
  await assert.rejects(client.send(() => {dispatched++;}), /already being checked/);
  assert.throws(() => client.begin("lot", "sale"), /pending/);
  finish();
  await first;
  assert.equal(dispatched, 1);
});

test("unrelated or malformed receipts cannot discard an uncertain order", async () => {
  const client = new RetailerRequest(storage(), () => "original-order");
  client.begin("lot", "sale");
  for (const change of [{idempotency_key: "other"}, {kind: "shipment"}, {lines: [{lot_id: "other", quantity: 1}]}, {allowed: "true"}, {blocked: null}]) {
    await assert.rejects(client.send(async request => ({...receipt(request), ...change})), /could not be confirmed/);
    assert.equal(client.pending.idempotency_key, "original-order");
  }
});

test("blocked requests are confirmed results and can be followed by a new request", async () => {
  let id = 0;
  const client = new RetailerRequest(storage(), () => String(++id));
  client.begin("recalled-lot", "sale");
  const result = await client.send(async request => ({...receipt(request), allowed: false, blocked: [{reason: "HOLD_RECALL"}]}));
  assert.equal(result.allowed, false);
  client.begin("eligible-lot", "shipment");
  assert.equal(client.pending.idempotency_key, "2");
});

test("storage failure prevents dispatch; a damaged saved request fails closed", () => {
  const client = new RetailerRequest({getItem: () => null, setItem: () => {throw Error("storage unavailable");}}, () => "id");
  assert.throws(() => client.begin("lot", "sale"), /storage unavailable/);
  assert.equal(client.pending, null);
  assert.throws(() => new RetailerRequest({getItem: () => '{"kind":"sale"}'}, () => "id"), /invalid/);
});
