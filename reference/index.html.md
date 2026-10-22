# Reference – Inspect Ranges

### Python API

|  |  |
|----|----|
| [inspect_ranges.host](../reference/host.html.md) | The range-host extension point: implement and register a custom backend for INSPECT_RANGES_HOST. |
| [inspect_ranges](../reference/inspect_ranges.html.md) | Challenges and goals (dataset, setup, scoring, verification), the goal types, and range definition loading. |
| [inspect_ranges.scanners](../reference/scanners.html.md) | Deterministic apparatus checking over sample transcripts, as inspect_scout scanners. |
| [inspect_ranges.types](../reference/types.html.md) | Range definition types, usable directly as sandbox configuration. |

### CLI

|  |  |
|----|----|
| [inspect-ranges applier](../reference/applier.html.md) | Serve realize/teardown/heartbeat and the guest relay for driver processes on this host. |
| [inspect-ranges build](../reference/build.html.md) | Build a range: realize, verify, capture, and prove its declared guest content. |
| [inspect-ranges daemon-bundle](../reference/daemon-bundle.html.md) | Build the byte-deterministic daemon bundle the realizer bakes into goldens. |
| [inspect-ranges devbox](../reference/devbox.html.md) | Provision and manage an inspect_ranges development box on EC2. |
| [inspect-ranges doctor](../reference/doctor.html.md) | Check that this machine can run and develop ranges. |
| [inspect-ranges down](../reference/down.html.md) | Tear down a project (idempotent, works from any process, after any crash). |
| [inspect-ranges evidence](../reference/evidence.html.md) | Work with evidence locations: verify a record’s chains and seals. |
| [inspect-ranges images](../reference/images.html.md) | Manage the golden image cache: derive, list, and prune. |
| [inspect-ranges mirror](../reference/mirror.html.md) | Mirror between locations: a whole source, a name, a pin, or a spec-selected build. |
| [inspect-ranges plan](../reference/plan.html.md) | Resolve a range directory or spec file into its immutable plan. |
| [inspect-ranges publish](../reference/publish.html.md) | Promote a built guest’s realized image, a cache golden, or the daemon artifact to a bare catalog name, or rewrite a location’s catalog list. |
| [inspect-ranges pull](../reference/pull.html.md) | Resolve and fetch a published build: by this spec’s hash, a spec path, or a name@sha256 pin. |
| [inspect-ranges push](../reference/push.html.md) | Publish the current range’s build (its manifest’s transitive closure) to a location. |
| [inspect-ranges reaper](../reference/reaper.html.md) | Reclaim expired host leases: teardown first, then CID and lease release. |
| [inspect-ranges render](../reference/render.html.md) | Render a range directory or spec file into its realization bundle. |
| [inspect-ranges schema](../reference/schema.html.md) | Print the JSON Schema for range.yaml to stdout. |
| [inspect-ranges up](../reference/up.html.md) | Realize a rendered bundle into a running, ready range. |
| [inspect-ranges validate](../reference/validate.html.md) | Validate range.yaml files, and a sibling challenges.yaml cross-referenced against the range, with complete diagnostics. |
