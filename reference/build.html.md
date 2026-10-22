# inspect-ranges build – Inspect Ranges

Build PATH (default `.`): realize, verify, capture, and prove the range’s declared guest content.

The build boots an egress-enabled variant of the range (runtime isolation is untouched), runs each host’s `provisioning` steps in declaration order, verifies every declared service and vulnerability against the live guests, captures each provisioned guest as a realized image, runs any declared behavioral checks against the captured artifacts, and records the build manifest that `plan`/`render`/`up`/the provider consume. Rebuilds are incremental per guest; an unchanged range is a cached no-op. `--keep` preserves the running range for diagnosis (and captures nothing). Full reference: the Building Ranges docs page.

#### Usage

``` text
inspect-ranges build [OPTIONS] [PATH]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--image-cache` | path | Image cache used for golden resolution. | None |
| `--recipe-cache` | path | Recipe cache for the resolution fallback after ./recipes/. | None |
| `--cid-base` | integer range (`3` and above) | First vsock CID (plan-time input; realizer batteries use 3000+). | `3` |
| `--keep` | boolean | Keep the built range running for inspection (success or failure); tear down with `inspect-ranges down`. | `Sentinel.UNSET` |
| `--uplink-network` | text | Docker network build-time egress masquerades onto (created when absent). | `ir-uplink` |
| `--build-nameserver` | text | Resolver handed to build guests (fleets forcing DNS through a VPC resolver are the norm, not the exception). | None |
| `--build-cache` | path | Builds cache where the range’s manifest lives. | None |
| `--reverify` | boolean | Boot and verify in full even when every build key matches the recorded manifest. | `Sentinel.UNSET` |
| `--readiness-timeout` | float | Per-guest readiness deadline in seconds (daemon answer, then cloud-init). | `300.0` |
| `--settle-probe` | text | Hostname each guest must resolve before its first recipe runs; pass ‘off’ to skip the gate (fleets whose resolver answers only internal names). | None |
| `--settle-timeout` | float | Seconds to wait for the settle probe per guest. | None |
| `--recipe-budget` | float | Whole-entrypoint budget per provisioning step, in seconds. | `1800.0` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
