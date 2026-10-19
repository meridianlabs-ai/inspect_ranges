# inspect-ranges render – Inspect Ranges

Render PATH (default `.`, a range directory or spec file) into its realization bundle.

#### Usage

``` text
inspect-ranges render [OPTIONS] [PATH]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--output`, `-o` | path | Bundle directory to write (must be empty or absent). | `Sentinel.UNSET` |
| `--image-cache` | path | Image cache used for digest resolution. | None |
| `--cpu-model` | text | N/A | `host-passthrough` |
| `--cid-base` | integer range (`3` and above) | First vsock CID (plan-time input; realizer batteries use 3000+). | `3` |
| `--evidence-capture` | boolean | Render the evidence-capture sidecar (per-segment pcap; evidence-v1). | `False` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
