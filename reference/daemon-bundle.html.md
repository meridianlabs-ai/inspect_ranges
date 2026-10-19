# inspect-ranges daemon-bundle – Inspect Ranges

Build the byte-deterministic daemon bundle the realizer bakes into goldens, or fetch the published one with `--pull`.

#### Usage

``` text
inspect-ranges daemon-bundle [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--output`, `-o` | directory | Directory receiving the bundle tar and its daemon.json sidecar. | `dist/daemon` |
| `--pull` | boolean | Fetch the published daemon bundle instead of building (no Go toolchain needed). | `Sentinel.UNSET` |
| `--from` | text | Location override for –pull; default is the configured search path (INSPECT_RANGES_REGISTRY). | None |
| `--sha256` | text | Out-of-band pin for –pull: the bundle digest publish day recorded; a served bundle that differs refuses. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
