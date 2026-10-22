# inspect-ranges publish – Inspect Ranges

The deliberate promotion act: a built guest’s realized image (or a cache golden, or the daemon artifact) becomes consumable at a location; image promotions update the location’s catalog list, and `--list` rewrites that list to an exact set of names.

#### Usage

``` text
inspect-ranges publish [OPTIONS] [SPEC]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--guest` | text | Built guest whose realized image promotes (reads the range directory’s manifest). | None |
| `--as` | text | The bare catalog name to publish under. | None |
| `--golden` | text | Promote a cache golden under its own name instead of a built guest. | None |
| `--daemon` | directory | Publish the daemon artifact directory (its bundle tar and daemon.json) under the reserved ‘daemon-bundle’ ref. | None |
| `--list` | text | Rewrite the destination’s catalog list to exactly these names (repeatable), each verified to resolve there first with its kind (image or range) detected from what the destination serves; image publishes append on their own, this flag covers renames, repairs, and adding pushed ranges to enumeration. | `Sentinel.UNSET` |
| `--to` | text | Destination location (the public org on publish day; any location form). | `Sentinel.UNSET` |
| `--image-cache` | path | Image cache holding the artifacts. | None |
| `--build-cache` | path | Builds cache holding the factory manifest (guest promotion). | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
