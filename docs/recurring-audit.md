# Recurring inventory recall audits

An audit is an advisory workflow, not an inventory transaction. It retrieves
current CPSC candidates for the imported snapshot, refreshes selected official
notices and records new candidates, changed sources, pending assessments and
changes in per-record advice. New candidates still require explicit selection.

## Small, explicit policy

The default is off. Review `discovery_plan`, then POST `audit_configure` with
`enabled`, `auto_ai`, `interval_seconds` (60–86400, default 3600) and the reviewed
`plan_hash` when enabling periodic work. The UI has the same controls in step 4.
Enabling monitoring also permits searches derived from future imported product
attributes; SKU, external IDs, quantity, warehouse and serial are not query terms.

The existing custom inbound adapter checks the local due flag every 60 seconds.
A due policy queues `audit_tick` through CPSCPoller → Triage → CPSCRefresh. A
manual `audit_now` follows that same source operation. This is actual IRIS
Production scheduling; the host and Production must remain running. Stopped
Codespaces are not a 24-hour monitoring service.

The service sets `%WaitForNextCallInterval=1` after input and reserves queue
delivery atomically before sending. This avoids a catch-up loop that could queue
the same due work many times. The due time is checked on the adapter's minute
boundary, so an interval is approximate and can include another minute of delay.

An inventory capture makes an enabled monitor due again. It does not fetch from
or mutate the source ERP automatically: the retailer must still provide a new
CSV/JSON capture through the import contract.

## Search, source refresh and AI

Each cycle uses the existing limit of eight inventory-derived queries and forty
candidates. It refreshes up to five selected notices, rotating the batch when
there are more. Failed queries, omitted work and changed inventory during a
cycle are recorded. A cycle never claims complete CPSC coverage. Search failure
or zero results never establishes safety.

AI is a separate explicit opt-in. Enabling it requires a live provider profile,
a key and confirmed Free Tier, with no paid fallback. At most one selected notice
and twenty associated pending records are investigated per cycle. The AI worker
rechecks the policy generation, source/inventory versions, duplicate-attempt
fingerprint and daily budget before dispatch. Automatic runs use the lower of
the existing daily cap and five; no cap is raised. Current completed assessments
are reused. Quantity-only changes do not invalidate product applicability.
Unchanged failed inputs require a manual investigation rather than repeated
automatic retries. New or changed product identity/source content can be assessed
again. A scheduled investigation uses the same native AI Hub agent and strict
`evidence-v2` validation as a manual investigation.

## History and receiving workflow

`GET /api/state` includes `monitor.config` and the ten latest cycle summaries.
Cycles record trigger, request/cycle ID, start/finish, query count, refreshed and
changed notices, new candidate IDs, pending evaluation counts, failures, run ID
and advisory differences. A stable manual request ID is idempotent. Cycles have
a single active lease, a 60-second repeat cooldown and a ten-minute recovery
limit, including manual-only work after an interrupted process.

The advisory JSON includes the monitor summary. Each item and CSV row includes
`audit_attention` and `audit_cycle_id`. An incomplete audit remains actionable in
the sample receiver even if an older assessment excluded that item from the
selected notices. It is not a stock-stop command. The receiver creates a local
review worklist only; no email, webhook or ERP write is performed.

## Validation scope

Portable tests cover policy consent, no-key behavior, schedule/import triggers,
idempotency, source changes/failures, late policy/input changes, duplicate native
dispatch, budget rejection, assessment reuse, manual retry and timeout recovery.
The [actual timer/native check](../research/evidence/iris-recurring-audit.json)
completed one genuine scheduled v7 investigation, kept quantity 47 and reused the
assessment in the next unchanged cycle without another inference. The
[native trace](../research/evidence/iris-recurring-audit-trace.json) correlates its
run and audit-cycle IDs. A subsequent [queue-spacing check](../research/evidence/iris-audit-throttle.json)
observed two ticks for two cycles, 119.79 seconds apart, with no inference.
The [final source-free IPM archive](../research/evidence/iris-ipm-audit-build109.json)
installed 21 classes and twelve source-matching modules on empty build 109.
These are private checks; registry publication is pending. Historical 154/v6 and
current v7 records are kept as distinct scopes.
