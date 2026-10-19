# inspect-ranges doctor – Inspect Ranges

Check that this machine can run and develop ranges.

Exits with status 1 if any check fails (warnings don’t fail).

With `--fix-script`, prints a reviewable shell script of the runnable fixes instead of the report, and exits 0; fixes that need human judgment are included as comments.

#### Usage

``` text
inspect-ranges doctor [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--json` | boolean | Output results as JSON. | `Sentinel.UNSET` |
| `--fix-script` | boolean | Print a shell script applying the runnable fixes for this machine’s failed checks (pipe it to `sudo sh`). | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
