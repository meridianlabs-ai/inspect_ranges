# inspect-ranges push – Inspect Ranges

Publish the current range’s build (its manifest’s transitive closure) to a location.

#### Usage

``` text
inspect-ranges push [OPTIONS] [SPEC]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--to` | text | Destination location (registry or OCI-layout directory). Default: the first configured registry (INSPECT_RANGES_REGISTRY). Pushing to the public org is the project publisher’s job, not a user move. | None |
| `--image-cache` | path | Image cache holding the build’s artifacts. | None |
| `--build-cache` | path | Builds cache holding the manifest to publish. | None |
| `--recipe-cache` | path | Recipe cache for resolving the manifest’s recipe bundles. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
