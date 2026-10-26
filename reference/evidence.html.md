# inspect-ranges evidence – Inspect Ranges

Work with evidence locations (see design/inspect-ranges/evidence-v1.md).

#### Usage

``` text
inspect-ranges evidence [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|  |  |
|----|----|
| [verify](#inspect-ranges-evidence-verify) | Replay the hash chains at LOCATION and name the first break. |

## inspect-ranges evidence verify

Replay the hash chains at LOCATION and name the first break.

LOCATION is a local directory or an `s3://bucket/prefix` evidence location (S3 credentials follow standard AWS resolution). Exits 0 when every writer replays cleanly, 1 on any break or when no manifests exist. An unsealed writer is reported loudly but is not itself a break unless a binding was supplied for it (the lifecycle seals on finalize and on reap, where reap-sealing is done by whichever party reaches the abandoned record: the surviving driver at teardown, or the reaper and `cli_cleanup` for a dead driver; unsealed-at-rest means none of them happened). With `--expect-seal` the writer’s result carries the full detection claim; without it, internal consistency only.

#### Usage

``` text
inspect-ranges evidence verify [OPTIONS] LOCATION
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--shallow` | boolean | Replay manifests, chains, and seals only (skip fetching chunk bytes). | `Sentinel.UNSET` |
| `--json` | boolean | Emit the full report as JSON. | `Sentinel.UNSET` |
| `--expect-seal` | text | Externally-held seal digest to bind against (repeatable, one per writer). DIGEST is the bare hex from the sample-store binding or its INFO log line; a leading `sha256:` prefix is accepted and stripped. With any binding supplied, a writer at the location that no –expect-seal names is itself a break (the binding records the complete writer set, so additions are detected). Without it, verification attests internal consistency only: the chain anchors everything at or below the seal, but a forged or absent seal, an added writer, or a record transplanted from another location, is not detectable from the location alone. | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
