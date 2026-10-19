# inspect-ranges plan – Inspect Ranges

Resolve PATH (default `.`, a range directory or spec file) into its immutable plan.

Unsupported constructs fail here, at planning, with the same diagnostics as `validate`.

#### Usage

``` text
inspect-ranges plan [OPTIONS] [PATH]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--json` | boolean | Emit the plan as JSON. | `Sentinel.UNSET` |
| `--image-cache` | path | Image cache used for digest resolution. | None |
| `--cpu-model` | text | N/A | `host-passthrough` |
| `--cid-base` | integer range (`3` and above) | First vsock CID (plan-time input; realizer batteries use 3000+). | `3` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
