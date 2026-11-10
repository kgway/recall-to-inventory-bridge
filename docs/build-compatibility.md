# Supported build and validation scope

The current target is **IRIS Community AI Hub 2027.1.0AI.109.0**, which the
[contest organizer accepts](https://community.intersystems.com/post/intersystems-programming-contest-ai-agents-interoperability-workflows).
Load the authorized EAP image and use the dedicated 109 profile described in the README.
Keep EAP archives and all base/derived images private. An in-place database upgrade
from an older EAP build is not established by these tests.

- Current v7: two selected genuine native DREO investigations on 109, one manual
  and one scheduled, with scoped ReadContext, validated quotes and unchanged stock.
- Historical v6: build 154 matched 36/36 selected synthetic labels; build 109
  matched 15/24, including nine conservative extra reviews caused by a Hatch quote.
  These are distinct prompts/case sets, not a population accuracy estimate.
- The no-key recorded course revalidates original v6 proposals. It is not fresh inference.
- The source-free IPM check on 109 compiled 21 classes and twelve matching Python
  modules. Source/archive installation does not establish registry installation.
- A separate public-registry `0.1.0` check on fresh build 109 instances also passed
  the snapshot/CPSC and recorded courses without a model key or checkout mount.
  See [IPM prerequisites](ipm.md) and the [installation scope](verification.md#installation).

See [verification](verification.md) and [native traces](traceability.md).
