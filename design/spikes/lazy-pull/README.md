# Spike: lazy image pull — HTTP backing files + copy-on-read

*Measures the registry-direct lazy-pull path from [image-distribution](../../inspect-ranges/image-distribution.md): a VM boots from a local qcow2 overlay whose **backing file is an HTTP URL** (qemu's curl block driver), with `copy_on_read=on` self-populating the overlay. nginx serves the image cache (Range requests required). Run on the m6i.metal devbox, 2026-10-02. `./run.sh` reproduces; `./run.sh down` tears down.*

## Verdict

**Booting straight from a URL costs ~0.4 s** vs a fully local image, with zero pre-download step — and the warm overlay makes the second boot local (7.2 s, 11 MB residual fetch). The mechanism works and even **resolves multi-layer backing chains over HTTP** (the served image was itself a 2 MB delta whose relative backing resolved against the URL base — the chained-qcow2 distribution model and lazy pull compose for free). One honest caveat about bytes, below.

## Measurements

| What | Result |
|---|---|
| Local backing boot → daemon ready | 9.8 s |
| **Lazy HTTP backing boot → daemon ready** | **10.2 s** (no pre-download) |
| Overlay self-populated by copy-on-read | 270 MB |
| Bytes fetched during first lazy boot | 771 MB (vs 628 MB total chain size — see caveat) |
| Warm second boot (same overlay) | 7.2 s, **11 MB** additional fetch |
| Chain over HTTP | 2 layers (delta + base), relative backing resolved against the URL base |

## The honest caveat: small images over-fetch

First-boot fetch (771 MB) *exceeded* the compressed chain size (628 MB, ~123%): a small compressed image's boot working set covers most of it, the curl driver's cluster reads overlap/repeat before copy-on-read catches up, and COR populates post-decompression so re-reads hit the network. For a small Linux golden, lazy pull **loses on bytes** vs just downloading — the wins are **time-to-first-boot** (download overlaps boot; no serialized pull step), the **self-warming cache** (second boot ~local), and the extrapolation that matters: for 12–20 GB Windows goldens the boot working set is a small fraction of the image, so the fetched/size ratio inverts decisively. Measure that when Windows images meet this path.

## Operational findings

- **`qemu-block-extra`** is required on Ubuntu for the curl/http block driver (packaged separately from qemu-system) — add to the range image recipe and note for doctor if this path ships.
- The compose-service DNS name didn't resolve inside the range container for qemu; the spike pins the server IP. Production would use a real registry endpoint anyway.
- `copy_on_read=on` is plumbed through virt-install as `--disk ...,driver.copy_on_read=on` (libvirt `<driver copy_on_read>`).
- The shared host-cache tier (one streamed copy serving many VMs) remains a design sketch: a middle cache layer populated via COR or `block-stream`, with per-VM overlays on top.

## Files

- `compose.yaml` — nginx image server + range container (with `qemu-block-extra`)
- `range/` — Dockerfile (net-compile recipe + curl block driver)
- `run.sh` — baseline vs lazy vs warm-second-boot, with nginx-log byte accounting
