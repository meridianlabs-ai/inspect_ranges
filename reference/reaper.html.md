# inspect-ranges reaper – Inspect Ranges

Reclaim expired host leases: teardown first, then CID and lease release.

Reclaims on expiry alone, never probing liveness: a healthy sample never expires because its driver renews independently. A failed teardown frees nothing and the lease stays findable for the next sweep. One-shot mode exits 1 if any teardown failed.

#### Usage

``` text
inspect-ranges reaper [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--state-dir` | path | Project state directory (default: the shared inspect-ranges state dir). | None |
| `--interval` | float range (`0` and above) | Seconds between sweeps; omitted means one sweep and exit. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
