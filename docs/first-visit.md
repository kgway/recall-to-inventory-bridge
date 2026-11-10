# First visit: inventory in, evidence-backed advice out

Try the same course as a first-time evaluator. No model API key is needed.
The inventory is a synthetic ERP export; CPSC candidates come from the real
public API. The bridge stores a local snapshot and returns advice. The existing
inventory system owns every stock, sale and shipment action.

[日本語](first-visit.ja.md) · [integration contract](inventory-integration.ja.md)
· [OpenAPI](../schemas/openapi.json).

Watch the [98-second operation demo](https://www.youtube.com/watch?v=kQNJ_kUx9tA)
before starting. Its final AI segment inspects a separately saved genuine run.

## Inspect a receiving workflow before setup

The [saved-output receiver](../README.md#inspect-the-output-before-installing-iris)
needs only Python. It turns a bundled advisory capture into three local review
tasks without an IRIS installation, a model key or network access. This is a
captured-output example. Follow the next section to use the actual IRIS UI and
retrieve current CPSC information.

## Start a separate no-key instance

Prepare Docker, Python and a privately obtained AI Hub Community image. The
current target is 2027.1.0AI.109.0. EAP archives and derived images must stay private.

```bash
docker image load -i /path/to/iris-community-2027.1.0AI.109.0-docker.tar.gz
docker image ls
docker tag <loaded-image-name> recall-guard-aihub:2027.1.0AI.109.0
python scripts/init_env.py
python scripts/judge_demo.py start --iris-build 109 --build
```

Open [the local app](http://localhost:52773/recall-guard/auth/RecallGuard.Home.cls).
Use SuperUser and IRIS_PASSWORD from your ignored local .env. The actual container
gets a blank model key and AGENT_MODE=disabled. Root live credentials and settings
are not changed. The separate project retains its own data; it never resets an
existing dataset. Snapshot and recorded-demo courses require different instances.

A fresh build needs the base image size plus 2 GiB of free Docker storage; reusing
an existing application image needs 2 GiB. Later starts can omit --build. Keep
--iris-build 109 on start, stop and verification for an explicit target; 109 is
also the default. Windows `start.ps1` uses the same isolated no-key path.
See the [build matrix](build-compatibility.md).

## The five-to-ten-minute course

1. Choose **Load sample export**. The rows are synthetic DREO, Hatch and Anker
   stock. Select **Preview import** and inspect the recognized columns and errors.
2. Choose **Import previewed snapshot**. Leading zeros, external IDs, warehouses,
   lot references and reported quantities survive. Imported stock has no sale or
   ship button. The source inventory is not changed.
3. Choose **Review search terms**. Read the exact terms that will go to CPSC,
   then choose **Search CPSC with these terms**. Retrieval runs in the Production
   without AI. Partial results, failed queries and limits are visible.
4. For the DREO candidate, choose **Load official evidence**. Inspect the captured
   API and official detail page under Recall evidence. Fresh AI is still disabled;
   the app does not label an unassessed candidate as confirmed or excluded.
5. Download **advisory JSON** or **CSV**. The existing workflow can consume
   CANDIDATES_FOUND, source record IDs, official links and explicit scope. JSON
   says authority=ADVISORY_ONLY and external_inventory_updated=false.

No result never proves safety. NO_MATCH_IN_SELECTED_NOTICES only excludes the
selected notices and captured attributes. It is not a general clearance.

## Keep checking for changes

Step 4 offers **Run audit now** and optional periodic checks. Review the search
terms first, choose an interval and save the settings. Actual IRIS adapter ticks
repeat candidate search and refresh up to five selected notices per cycle. The
history shows changes, incomplete work and pending assessments. AI stays disabled
without a provider key; a PARTIAL cycle can mean assessment remains pending.
This is source monitoring, not a stock operation or an automatic inventory import.
The host and Production must remain running. Minute polling makes timing approximate.
If a background tab has stale results, reload to read the stored current history.
Disable periodic checks when finished. See the [audit contract](recurring-audit.md).

## A receiving workflow you can run

```bash
python scripts/bridge_sync.py export --format json --output .artifacts/advisories-001.json
python examples/review_consumer.py --advisories .artifacts/advisories-001.json --output .artifacts/worklist-001.json
```

The receiver creates local review tasks. It does not contact an ERP or write stock.
Use a new output filename each time; outputs are never silently overwritten.
The integration guide covers field mapping, idempotent capture IDs, source ordering
and HTTP 409 conflicts. A vendor-specific production connector is not supplied.

## Optional recorded AI and consumer simulator

On a different empty instance, choose **Start recorded investigation demo**.
The Production verifies the pinned original context and revalidates genuine
historical v6 proposals. The UI labels it RECORDED INVESTIGATION DEMO. Original
run IDs, tool hashes and historical usage remain provenance, not new inference.

The four sample shortcuts open manufacture boundaries, earlier manufacture,
missing date and adapter identity. Sale/Ship applies only to a local synthetic
consumer simulator. Held examples are rejected; an eligible simulated sale consumes
one simulated unit. No external inventory is connected. This course cannot be
mixed with imported snapshots or used to replenish prior simulated sales.

The optional verify_recorded_demo.py --iris-build 109 check sends five new synthetic
orders and consumes one eligible unit. Use a new --output filename and ensure it
points to the separate recorded course. It does not prove fresh AI Hub execution.

## Stop

```bash
python scripts/judge_demo.py stop --iris-build 109
```

Stop any remote host and SSH forwarding too when using a private host.
See the [verification record](verification.md).
