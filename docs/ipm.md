# IPM installation

## Prerequisites

- A dedicated AI Hub instance and an Interoperability-enabled namespace named
  `RECALLGUARD`. The installer refuses another namespace or a running Production.
  It does not create a namespace, database, user or model credential.
- IRIS 2026.3 or later **with `%AI.Agent`**. Plain IRIS without AI Hub is insufficient.
  Builds 154 (2026.3) and 109 (2027.1) have passed the archive checks described above.
  Use a fresh dedicated instance when changing release streams.
- IPM 0.10.10 or later installed in `RECALLGUARD`; the tested client is pinned below.
- An existing IRIS account with permission to install classes, configure the two
  application web paths and operate the Production.

Keep this evaluation separate from an operational IRIS instance. The two web
paths are instance-wide: `/recall-guard` and `/recall-guard/auth`. Existing paths
owned by another namespace/dispatch class are refused by the preflight check.

For a fresh dedicated EAP container, first mount its own persistent volume at
`/usr/irissys/mgr/recallguard-data`. The checked-in `docker/merge.cpf` creates the
two application databases and Interoperability namespace used by these tests:

```bash
docker cp docker/merge.cpf <container>:/tmp/recall-guard-namespace.cpf
docker exec --user root <container> chown irisowner:irisowner /usr/irissys/mgr/recallguard-data
docker exec <container> iris merge IRIS /tmp/recall-guard-namespace.cpf
```

Use this only while preparing an empty, dedicated instance. The IPM installer
itself deliberately does not change instance-wide namespace/database setup.
The code database can be regenerated from source; retain the data volume and
plan separate database backups for any valuable records.

## Install the client and application

Download the official [IPM 0.10.10 release](https://github.com/intersystems/ipm/releases/tag/v0.10.10)
asset `zpm-0.10.10.xml` and verify its SHA-256:

```text
daa2adabd66b488f57187d29712e54b0c25bbe000794fbf2a35a882c458b788a
```

In an IRIS terminal, in the prepared namespace:

```objectscript
zn "RECALLGUARD"
do $SYSTEM.OBJ.Load("/path/to/zpm-0.10.10.xml","ck")
zpm "load /path/to/recall-to-inventory-bridge -v"
zpm "list recall-to-inventory-bridge"
```

Require successful Compile, Configure and Activate phases and the listed package
version `0.1.0`. A terminal shell exit code alone is insufficient. The install
does not start a Production, seed inventory, fetch CPSC, change passwords or call
an LLM. It creates the same password-authenticated REST and CSP-login applications
as the Docker installation, including the dedicated cookie path and CSRF setting.

For a locally exported distribution, `zpm "load /path/to/package.tgz -v"` uses the
same installation path. To export source already loaded into a stopped instance:

```objectscript
zpm "package recall-to-inventory-bridge -path /tmp/recall-to-inventory-bridge -v"
```

IPM prints the generated archive path. This creates an archive locally and does
not publish it. Keep private settings and EAP files out of the package.

Start explicitly:

```objectscript
do $SYSTEM.Status.DisplayError(##class(RecallGuard.Package).Start())
```

Open `/recall-guard/auth/RecallGuard.Home.cls` on the instance's existing web
server and use an existing account. For a first visit with inference disabled,
follow the [snapshot course](first-visit.md): **Load sample export**, preview and
import, retrieve CPSC candidates, select evidence and export advice. Recurring
source audits also need no model key. On a different empty instance,
**Start recorded investigation demo** revalidates captured genuine proposals.
The courses preserve existing data and cannot replace or mix with each other.

Live inference uses the same environment settings as the Docker path:
`GEMINI_API_KEY`, `GEMINI_MODEL`, `FREE_TIER_CONFIRMED`, `AGENT_MODE` and
`MAX_AGENT_RUNS_PER_DAY`. Confirm the provider's Free Tier/no-billing configuration
before enabling it. Environment changes require restarting the IRIS process or
recreating the container with the intended configuration. No paid fallback exists.

## Installed files and removal

IPM copies only the twelve explicitly enumerated Python source files and the selected application assets
under the instance's `mgr/python/recall_guard/` directory. The assets include the
UI, synthetic inventory, expected labels, three captured public CPSC response
directories and MPL license. Runtime database records, keys, `.env`, EAP images,
local Python caches are not package resources.
The explicitly bundled recorded-demo fixture contains public source snapshots,
synthetic inventory and original genuine proposals, not a mutable application database.
The Docker path keeps its existing `/opt/recall-guard` layout.

Ordinary IPM removal is refused while the Production is running or application
records exist. This was checked on the actual isolated instance. It prevents a
routine uninstall from silently taking away the demo's saved records; it does
not replace backups or protect against an administrator deleting files/classes
manually or overriding package operations. Plan retention before removal.

The Python directory belongs to this application and is shared within an IRIS
instance. The current release supports one dedicated `RECALLGUARD` installation
per instance. Stop the Production before reinstalling; do not treat a source load
as an online, atomic upgrade of a running service.


References: [IPM client](https://github.com/intersystems/ipm), [manifest documentation](https://github.com/intersystems/ipm/wiki/03.-IPM-Manifest-(module.xml)).
