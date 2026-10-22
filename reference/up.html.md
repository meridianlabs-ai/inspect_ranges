# inspect-ranges up – Inspect Ranges

Realize a rendered BUNDLE into a running, ready range.

Verifies every manifest digest before acting (tampered or incomplete bundles refuse), brings up the hardened range container on the bundle’s own compose project, boots every guest per `boot.json`, and waits on every readiness probe. The hardened range image is required; there is no bypass.

#### Usage

``` text
inspect-ranges up [OPTIONS] [BUNDLE]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--from-spec` | path | Render SPEC into a temporary bundle first, then apply it (composition sugar; the applier still consumes only the verified bundle). | None |
| `--project` | text | Compose project name (default: `ir-<range>-<spec digest>`). | None |
| `--image-cache` | path | Image cache the bundle’s image digests re-verify against. | None |
| `--cid-base` | integer range (`3` and above) | First vsock CID when rendering `--from-spec` (plan-time input). | `3` |
| `--readiness-timeout` | float | Per-guest readiness deadline in seconds (daemon answer, then cloud-init). | `300.0` |
| `--keep` | boolean | Keep a failed range running for inspection instead of tearing it down. | `Sentinel.UNSET` |
| `--uplink-network` | text | Deployment-supplied uplink network, for ranges that request egress. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
