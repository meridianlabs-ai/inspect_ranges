# inspect-ranges images – Inspect Ranges

Manage the golden image cache.

#### Usage

``` text
inspect-ranges images [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|  |  |
|----|----|
| [derive](#inspect-ranges-images-derive) | Derive a daemon-baked golden from a digest-pinned vendor cloud image. |
| [derive-windows](#inspect-ranges-images-derive-windows) | Install a sysprep’d Windows golden from digest-pinned eval media (windows-ad-v1). |
| [list](#inspect-ranges-images-list) | List the cache: managed goldens with provenance, then unmanaged files. |
| [pull](#inspect-ranges-images-pull) | Fetch a published catalog image’s chain into the cache (sticky thereafter: later builds keep resolving the cached artifact until an explicit refresh). |
| [refresh](#inspect-ranges-images-refresh) | The explicit move-forward act: re-resolve bare names against the search path and replace cached chains that moved; the next build’s keys change accordingly. |
| [prune](#inspect-ranges-images-prune) | Reclaim realized images no manifest references, plus capture temps and orphan sidecars; `--chains` extends to unreferenced goldens and vendor bases (pulled chains accounted exactly like built ones). |
| [pin](#inspect-ranges-images-pin) | Write the fleet pin file (every catalog name’s current root digest); hosts consuming it via INSPECT_RANGES_PIN_FILE refuse a catalog that moved past the pinned state. |

## inspect-ranges images derive

Derive a daemon-baked golden from a digest-pinned vendor cloud image.

Offline derivation (Ubuntu noble vendor images in v1): verifies the vendor digest, bakes the pinned control daemon, disables ssh and the resolved stub listener, and records provenance beside the golden. Idempotent: re-running with the same inputs is a cache hit.

#### Usage

``` text
inspect-ranges images derive [OPTIONS] VENDOR
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--sha256` | text | Required digest pin for the vendor image (hex or sha256:-prefixed). | `Sentinel.UNSET` |
| `--name` | text | Golden name (default: -golden). | None |
| `--image-cache` | path | Image cache the golden is derived into. | None |
| `--daemon-bundle` | path | Directory holding the daemon-bundle artifact and its daemon.json (default: the shared artifact cache; publish one with `inspect-ranges daemon-bundle`). | None |
| `--daemon-sha256` | text | Out-of-band pin for the daemon bundle digest (printed by `inspect-ranges daemon-bundle` at publish). Without it, the sidecar proves internal consistency only. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges images derive-windows

Install a sysprep’d Windows golden from digest-pinned eval media (windows-ad-v1).

A one-shot hardened range container runs the unattended install: viostor in WinPE, virtio guest tools and the vsock control daemon at first logon (compiled in-guest from the daemon bundle’s Windows sources), then `sysprep /generalize /shutdown`. Clones specialize per boot from the render-emitted unattend seed. Windows artifacts are LOCAL ONLY (recipes-not-images, the ratified posture); nothing Windows-derived publishes anywhere. Idempotent on the same media, daemon, and password pins.

#### Usage

``` text
inspect-ranges images derive-windows [OPTIONS] ISO
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--sha256` | text | Required digest pin for the Windows install ISO (hex or sha256:-prefixed). | `Sentinel.UNSET` |
| `--virtio-iso` | path | The virtio-win driver ISO (viostor for WinPE, guest tools, the viosock driver). | `Sentinel.UNSET` |
| `--virtio-sha256` | text | Required digest pin for the virtio-win ISO. | `Sentinel.UNSET` |
| `--name` | text | Golden name. | `windows-2022` |
| `--admin-password` | text | The golden’s built-in Administrator password (scenario content; the control plane is the vsock daemon as SYSTEM). Defaults to the documented constant. | None |
| `--image-cache` | path | Image cache the golden is installed into. | None |
| `--daemon-bundle` | path | Directory holding the daemon-bundle artifact (its windows/ sources compile in-guest). | None |
| `--daemon-sha256` | text | Out-of-band pin for the daemon bundle digest. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges images list

List the cache: managed goldens with provenance, then unmanaged files.

#### Usage

``` text
inspect-ranges images list [OPTIONS]
```

#### Options

| Name            | Type    | Description                 | Default          |
|-----------------|---------|-----------------------------|------------------|
| `--image-cache` | path    | Image cache to list.        | None             |
| `--help`        | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges images pull

Fetch a published catalog image’s chain into the cache (sticky thereafter: later builds keep resolving the cached artifact until an explicit refresh).

#### Usage

``` text
inspect-ranges images pull [OPTIONS] NAME
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--from` | text | Location override; default is the configured search path (INSPECT_RANGES_REGISTRY). | None |
| `--image-cache` | path | Image cache the chain materializes into. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges images refresh

The explicit move-forward act: re-resolve bare names against the search path and replace cached chains that moved; the next build’s keys change accordingly.

#### Usage

``` text
inspect-ranges images refresh [OPTIONS] NAMES...
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--from` | text | Location override; default is the configured search path (INSPECT_RANGES_REGISTRY). | None |
| `--image-cache` | path | Image cache whose chains move forward. | None |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges images prune

Reclaim realized images no manifest references, plus capture temps and orphan sidecars; `--chains` extends to unreferenced goldens and vendor bases (pulled chains accounted exactly like built ones).

Build success already garbage-collects its own range (keeping the previous generation for rollback); prune covers the rest: generations stranded by refused manifests or crashes, ranges whose builds are gone, `.capturing` and `.pulling` temps, and sidecars whose image vanished. The chain tier’s liveness scan: a golden survives while any realized sidecar names it, any build manifest records it, or a live project boots it; a vendor base survives while any surviving golden’s provenance names it. Reports by default; `--yes` deletes. Refuses while registered projects exist unless `--force` (running projects’ files are excluded either way).

#### Usage

``` text
inspect-ranges images prune [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--image-cache` | path | Image cache to prune. | None |
| `--build-cache` | path | Builds cache whose manifests define liveness. | None |
| `--yes` | boolean | Delete instead of reporting. | `Sentinel.UNSET` |
| `--force` | boolean | Prune even while registered projects exist (their referenced files are still excluded). | `Sentinel.UNSET` |
| `--recipe-cache` | path | Recipe cache whose stranded pull stagings are reclaimed. | None |
| `--chains` | boolean | Also reclaim goldens and vendor bases nothing references (the distribution tier): eviction is by whole chain, never a backing out from under a dependent. | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges images pin

Write the fleet pin file (every catalog name’s current root digest); hosts consuming it via INSPECT_RANGES_PIN_FILE refuse a catalog that moved past the pinned state.

#### Usage

``` text
inspect-ranges images pin [OPTIONS]
```

#### Options

| Name     | Type    | Description                  | Default          |
|----------|---------|------------------------------|------------------|
| `--from` | text    | The catalog location to pin. | `Sentinel.UNSET` |
| `--out`  | path    | Pin file to write.           | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit.  | `Sentinel.UNSET` |
