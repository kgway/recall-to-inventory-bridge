// SPDX-License-Identifier: MPL-2.0
"use strict";

// Keep an uncertain request across reloads in this tab. A retry must never mint
// another order ID merely because the server's acknowledgement was lost.
class RetailerRequest {
  constructor(storage, uuid) {
    this.storage = storage;
    this.uuid = uuid;
    this.key = "rib.pending-retailer-request.v1";
    this.busy = false;
    const saved = storage.getItem(this.key);
    this.pending = saved ? JSON.parse(saved) : null;
    if (this.pending && !this.validRequest(this.pending)) {
      throw Error("The saved retailer request is invalid. Keep this tab and inspect its request history before sending another order.");
    }
  }

  validRequest(value) {
    return typeof value.idempotency_key === "string" && value.idempotency_key.length > 0 &&
      ["sale", "shipment"].includes(value.kind) && Array.isArray(value.lines) && value.lines.length === 1 &&
      typeof value.lines[0]?.lot_id === "string" && value.lines[0].lot_id.length > 0 && value.lines[0].quantity === 1;
  }

  begin(lotId, kind) {
    if (this.pending || this.busy) throw Error("Resolve the pending retailer request before sending another order.");
    const request = {idempotency_key: this.uuid(), kind, lines: [{lot_id: lotId, quantity: 1}]};
    if (!this.validRequest(request)) throw Error("Invalid retailer request.");
    // If persistence fails, do not send a request that cannot survive a reload.
    this.storage.setItem(this.key, JSON.stringify(request));
    this.pending = request;
  }

  acknowledge(receipt) {
    const request = this.pending;
    if (!request || receipt?.idempotency_key !== request.idempotency_key ||
        receipt.kind !== request.kind || !Array.isArray(receipt.lines) || receipt.lines.length !== 1 ||
        receipt.lines[0]?.lot_id !== request.lines[0].lot_id || receipt.lines[0]?.quantity !== request.lines[0].quantity ||
        typeof receipt.allowed !== "boolean" || !Array.isArray(receipt.blocked)) {
      throw Error("The retailer result could not be confirmed. Retry the saved request to retrieve its original result.");
    }
    this.storage.removeItem(this.key);
    this.pending = null;
    return receipt;
  }

  async send(transport) {
    if (!this.pending) throw Error("No pending retailer request.");
    if (this.busy) throw Error("The saved request is already being checked.");
    this.busy = true;
    try {
      return this.acknowledge(await transport(this.pending));
    } finally {
      this.busy = false;
    }
  }
}

if (typeof module !== "undefined" && module.exports) module.exports = {RetailerRequest};
