# inspect-ranges pull – Inspect Ranges

Resolve and fetch a published build: bare (this directory’s range.yaml, matched by its exact normalized-spec hash), a spec path, or the no-spec `name@sha256:...` form (Journey B’s pulling-without-a-spec-in-hand).

#### Usage

``` text
inspect-ranges pull [OPTIONS] [TARGET]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--pin` | text | Pull an exact published root by digest (<name@sha256> form: pass the sha256:… digest) instead of resolving by this spec’s hash. | None |
| `--from` | text | Location override; default is the configured search path (INSPECT_RANGES_REGISTRY, first match wins). | None |
| `--image-cache` | path | Image cache artifacts materialize into. | None |
| `--build-cache` | path | Builds cache the pulled manifest lands in. | None |
| `--recipe-cache` | path | Recipe cache pulled bundles extract into. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
