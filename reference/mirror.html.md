# inspect-ranges mirror – Inspect Ranges

Mirror between locations: bare (whole source, the seed/sync move), a NAME, a `name@sha256:` pin, or a spec path (the cross-group move: the local range.yaml selects the source build exactly). A spec target must LOOK like a path (`.`, `./dir`, `/abs`, or `*.yaml`); a bare word is always a name, never a local directory, so dispatch is identical in every working directory.

#### Usage

``` text
inspect-ranges mirror [OPTIONS] [TARGET]
```

#### Options

| Name     | Type    | Description                 | Default          |
|----------|---------|-----------------------------|------------------|
| `--from` | text    | Source location.            | `Sentinel.UNSET` |
| `--to`   | text    | Destination location.       | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
