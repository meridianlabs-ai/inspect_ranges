# inspect-ranges down – Inspect Ranges

Tear down PROJECT (idempotent, works from any process, after any crash).

#### Usage

``` text
inspect-ranges down [OPTIONS] [PROJECT]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--all` | boolean | Tear down every ir- project on this host (never touches other prefixes). | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
