# Recall-to-Inventory Bridge

Connect US CPSC recall evidence to the inventory systems a retailer already uses.
Import CSV/JSON stock snapshots, discover candidate notices, investigate selected
evidence with native IRIS AI Hub, and return versioned **advisories**. The existing
ERP/WMS/POS and its operators own stock, sale and shipment actions.

[First visit](docs/first-visit.md) · [日本語](docs/first-visit.ja.md) ·
[Integration contract](docs/inventory-integration.ja.md) · [OpenAPI](schemas/openapi.json) ·
[Implementation map](#implementation-map)

[Watch the 98-second operation demo](https://www.youtube.com/watch?v=kQNJ_kUx9tA):
real CPSC retrieval, synthetic inventory and a separately labelled saved native AI run.
[Download the identical MP4](https://github.com/kgway/recall-to-inventory-bridge/releases/download/v0.1.0/recall-to-inventory-bridge-demo.mp4)
without signing in.

## Inspect the output before installing IRIS

Read the [captured advisory feed](examples/advisories/observed-keyless-advisories.json)
and its [receiving worklist](examples/advisories/observed-review-worklist.json).
These are saved real retrieval outputs over synthetic stock, not a running demo.
With a source checkout and Python, the example receiver can create a worklist locally:

```bash
python examples/review_consumer.py --advisories examples/advisories/observed-keyless-advisories.json --output .artifacts/my-review-worklist.json
```

Open the resulting JSON: three tasks retain source-system IDs, leading-zero record
references and recall candidates; `stock_action_performed` stays `false`. This
command reads the bundled capture, makes no network or model calls, and refuses
to overwrite an existing output. It demonstrates how an existing review process
can consume the bridge's advice. Continue below to run the actual IRIS workflow.

| Experience | Required setup | What it exercises |
| --- | --- | --- |
| Saved-output receiver above | Python only | Local tasks from a bundled advisory capture |
| Snapshot course below | AI Hub 109 and Docker; no model key | Real CPSC retrieval, inventory import, recurring source checks and advice |
| Optional recorded course | A separate empty AI Hub instance; no model key | Evidence-policy revalidation of saved genuine proposals and a synthetic consumer simulator |
| Optional live investigation | AI Hub and an explicitly enabled provider key | A new native `%AI.Agent` investigation; provider limits apply |

## Workflow

1. Preview a CSV/JSON export from an existing system. Inspect column mappings and
   row errors, then import a separate inventory snapshot. Leading-zero IDs, source
   references, lot/warehouse identity and reported quantities are preserved.
2. Review the exact public product terms to send to CPSC. The Interoperability
   Production retrieves candidate notices without a model key. A candidate is
   not a confirmed match; a zero-result search never proves product safety.
3. Select notices to acquire official evidence. Native `%AI.Agent` investigates
   associated records with one scoped read tool when inference is explicitly enabled.
4. Read versioned JSON/CSV advisories containing citations, missing fields, source
   versions and run provenance. The example receiver creates a local review worklist.
5. Optionally enable recurring recall audits. The custom IRIS adapter repeats
   searches and refreshes selected sources. New candidates require review;
   automatic AI is a separate opt-in, capped at one investigation per cycle.

![CPSC candidates from imported synthetic stock](docs/images/inventory-cpsc-candidates.png)

## Quick start without an API key

Requirements: Docker with Linux containers, Python, and an authorized private
**IRIS Community AI Hub 2027.1.0AI.109.0** image from the
[InterSystems EAP portal](https://evaluation.intersystems.com/Eval/early-access/AIHub).
Do not publish EAP archives or base/derived Docker images.

```bash
docker image load -i /path/to/iris-community-2027.1.0AI.109.0-docker.tar.gz
docker image ls
docker tag <loaded-image-name> recall-guard-aihub:2027.1.0AI.109.0
python scripts/init_env.py
python scripts/judge_demo.py start --iris-build 109 --build
```

Open [the local app](http://localhost:52773/recall-guard/auth/RecallGuard.Home.cls).
Sign in with `SuperUser` and the generated `IRIS_PASSWORD` in the ignored local
`.env`. The helper starts a separate no-key instance with inference disabled.
It retains its own data and does not reset an existing dataset.

Choose **Load sample export → Preview import → Import previewed snapshot →
Review search terms → Search CPSC with these terms**. Select an official notice,
load its evidence, then download advisory JSON/CSV. Follow the
[first-visit guide](docs/first-visit.md) for screenshots, limits and the separate
optional recorded AI course.

```bash
python scripts/judge_demo.py stop --iris-build 109
```

The package is also available from the public IPM registry. In a prepared,
dedicated `RECALLGUARD` namespace with the community registry enabled, run
`zpm "install recall-to-inventory-bridge"`. Follow [IPM installation](docs/ipm.md)
for namespace preparation, registry setup and explicit Production startup.

## Evidence and authority

One IRIS instance contains an actual Interoperability Production, native AI Hub,
Embedded Python, SQL persistence, authenticated REST and a browser UI. There is
no additional database, queue service or LLM framework. Native messages carry
source retrieval, context access, investigation and validation.

The agent has no external action tools. Validation checks exact source quotes,
identifiers, manufacturing ranges, component/generation scope and source/inventory
versions. Unsupported claims become review advice. Confidence does not grant clearance.

The bridge has no external inventory writeback connector. Imported snapshots
cannot call the optional local synthetic sale/shipment simulator. The receiving
system owns real-world action authority.

The [trace guide](docs/traceability.md) implements
[Community Opportunity DPI-I-689](https://ideas.intersystems.com/ideas/DPI-I-689):
native messages correlate run IDs, prompt/policy versions, tool context hashes and
provider-returned usage. Per-provider HTTP spans and SDK-internal retries are
outside the instrumentation. [Verification](docs/verification.md) distinguishes
portable tests, recorded validation and genuine native investigations.

## Implementation map

The native agent interprets recall scope, including manufacturing windows,
component identity and missing qualifiers. Its proposals carry exact source quotes.
The separate validator checks those quotes and captured versions before storing
advice. Candidate retrieval alone does not produce an AI assessment.

| Component | Implementation | Inspect or reproduce |
| --- | --- | --- |
| Interoperability routing | [Production](src/RecallGuard/Production.cls), [Triage](src/RecallGuard/Process/Triage.cls), [CPSC operation](src/RecallGuard/Operation/CPSC.cls) | [English architecture and message flow](docs/architecture.md) |
| Native AI Hub and scoped tool | [`%AI.Agent` subclass](src/RecallGuard/Agent/Investigator.cls), [ReadContext tool](src/RecallGuard/Agent/Tools.cls), [Gateway](src/RecallGuard/Gateway.cls) | [Genuine v7 investigation](research/evidence/iris-advisory-v7-native.json) |
| Embedded Python and evidence validation | [Embedded Python bridge](src/RecallGuard/Backend.cls), [policy](python/recall_guard/policy.py), [engine](python/recall_guard/engine.py) | [Observed checks and limits](docs/verification.md) |
| Custom adapter and recurring audits | [Inbound adapter](src/RecallGuard/Adapter/CPSCInbound.cls), [service](src/RecallGuard/Service/CPSC.cls), [monitor](python/recall_guard/monitor.py) | [Actual native timer and unchanged-cycle reuse](research/evidence/iris-recurring-audit.json) |
| Native traceability, DPI-I-689 | [Run and session correlation guide](docs/traceability.md) | [Saved native message metadata](research/evidence/iris-recurring-audit-trace.json); use your own run IDs in a fresh instance |
| IPM deployment | [Manifest](module.xml), [installation and registry configuration](docs/ipm.md) | [Source/archive and public-registry verification scopes](docs/verification.md#installation) |
| Existing-system handoff | [JSON/CSV contract](schemas/openapi.json), [example receiver](examples/review_consumer.py) | [Captured advice and worklist](examples/advisories/observed-review-worklist.json) |

## Live inference and recurring audits

Live inference is opt-in through `GEMINI_API_KEY`, `FREE_TIER_CONFIRMED=true` and
`AGENT_MODE=live`. Verify your provider's Free Tier/no-billing configuration first.
There is no paid fallback. The default cap is five investigations per UTC day;
SDK/provider request counts can be higher. Never commit credentials.

The [audit contract](docs/recurring-audit.md) describes intervals, source changes,
assessment reuse and incomplete coverage. Monitoring requires a running IRIS host
and Production. It does not fetch inventory from an ERP or change external stock.

## Limits and license

This evaluation supports 100 inventory records, a 100,000-byte input, eight
queries per search, 40 candidates and 40 selected notices. It is not a complete
CPSC index or a general safety clearance. FDA and other national feeds, enterprise
catalogue synchronization and vendor-specific ERP connectors are outside this version.

Original code is **MPL 2.0**. CPSC material and InterSystems software retain their
own terms. Internal `RecallGuard` identifiers preserve technical compatibility.

[Architecture](docs/architecture.md) · [Build compatibility](docs/build-compatibility.md) ·
[Release notes](docs/releases/0.1.0.md) · [Source license](LICENSE)
