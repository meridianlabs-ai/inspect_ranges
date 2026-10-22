# inspect-ranges applier – Inspect Ranges

Serve realize/teardown/heartbeat and the guest relay for driver processes on this host.

Runs the doctor-readiness subset at startup and refuses to serve unhealthy. A restart loses the replay log, relay map, and admission charges (recorded v1 limitation); disk-driven teardown (the reaper, `inspect-ranges down`) is the recovery.

#### Usage

``` text
inspect-ranges applier [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--socket` | path | Unix socket to serve on (created 0600 in a 0700 directory). | `Sentinel.UNSET` |
| `--state-dir` | path | Project state directory (default: the shared inspect-ranges state dir). | None |
| `--image-cache` | path | Image cache that realize verifies bundle image digests against. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
