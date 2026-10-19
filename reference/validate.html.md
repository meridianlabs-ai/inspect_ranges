# inspect-ranges validate – Inspect Ranges

Validate `range.yaml` files against schema v0.1 (default: the current directory’s).

Reports every detectable issue in each file at once, with source positions and hints. Each PATH may be a spec file or a range directory. Exits with status 1 if any file is invalid.

#### Usage

``` text
inspect-ranges validate [OPTIONS] [PATHS]...
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--json` | boolean | Emit one JSON report per file instead of text. | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
