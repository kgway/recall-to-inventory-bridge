# Verification and limitations

The application uses real public CPSC data and synthetic inventory. The records
below describe selected observed checks, not production accuracy or complete recall
coverage. Published JSON extracts retain technical outputs and original timestamps.

## Genuine native AI Hub

- [Manual v7 advisory investigation](../research/evidence/iris-advisory-v7-native.json):
  one synthetic DREO record on build 109; actual native AI Hub and scoped ReadContext,
  exact-quote validation, MATCH_RECALL and unchanged reported quantity.
- [Native message trace](../research/evidence/iris-advisory-v7-trace.json): original
  run `734900d502544860ad9c608fec8c7ed1`, sessions 55/57/61, provider-returned usage.
- [Scheduled workflow](../research/evidence/iris-recurring-audit.json) and
  [native trace](../research/evidence/iris-recurring-audit-trace.json): original
  run `6e9d0b1500614c66b0dd5da25e41f7f9`; the next unchanged cycle reused the assessment.
- [Queue spacing](../research/evidence/iris-audit-throttle.json): separate actual
  adapter cycles, no fresh inference, unchanged stock.

These current-prompt checks cover two selected records, not a new 36-case result.
The [historical native trace](../research/evidence/iris-visual-trace.json) is a
separate older 154/v5 run. Refer to [traceability](traceability.md) for reproduction.

## Recorded validation and regression data

The byte-pinned fixture includes original v6 context/proposals and synthetic lots.
Its loader verifies the original context hash and revalidates with the evidence
policy. It never calls a model. Historical 154/v6 labels matched 36/36; separate
109/v6 live results matched 15/24, with nine conservative extra reviews. The
[109 regression data](../research/evidence/iris-build109-native.json) preserves
the observed Hatch proposal/quote failure used by the portable tests.

## Installation

The [source-free IPM check](../research/evidence/iris-ipm-audit-build109.json)
compiled 21 classes and verified twelve Python modules on 109, with separate
snapshot/advisory and recorded courses, default-off monitoring and data-removal
guards. This was source/archive installation, not a public-registry install.

Public-registry installation of `0.1.0` was also checked on fresh build 109
instances, without mounting an application checkout. All twelve installed Python
modules matched the registry artifact. The recorded course matched 36 expected
decisions without new inference. A separate snapshot course preserved leading-zero
IDs and quantities, rejected sale requests, retrieved a real CPSC candidate and
its official evidence, and exported advisory JSON/CSV with inference disabled.
Monitoring stayed off by default, and ordinary removal refused saved records.
See [IPM installation](ipm.md) for the required registry configuration.

## Portable checks

```bash
python -m unittest discover -s tests
node --test tests/test_retailer_request.cjs
```

Set `PYTHONPATH=python` first (`$env:PYTHONPATH='python'` in PowerShell or
`export PYTHONPATH=python` in a POSIX shell). These tests cover domain logic,
source parsing, imports, advice, monitoring and recorded-fixture guards. They do
not prove an IRIS installation or execute a fresh AI investigation.

No-key retrieval still needs network access to CPSC. Live inference is separately
opt-in. Monitoring requires the host and Production to stay running. No stock or
external inventory action is authorized by any verification result.
