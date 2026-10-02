---
type: document
title: "Image distribution: content-addressed qcow2 layers, lazy block pull, and platform-native caches"
audience: inspect-ranges development
status: draft
tags: [inspect-ranges, images, distribution, registry, oras, decision]
timestamp: 2026-10-02
---

# Image distribution: content-addressed qcow2 layers, lazy block pull, and platform-native caches

*Prompted by the Proxmox provider author: "I'm super curious whether you can find a solution to the problem of the large binary images we end up needing to ship around. Docker 'solved' this by using overlayfs; in the proxmox provider there are template VMs and linked clones, but it's still not ideal." The reframe this doc builds on: Docker solved distribution with **content-addressed layers**; overlayfs is only the runtime view. Templates + linked clones replicate the runtime half; the missing half is the distribution model — and qcow2 has the native primitive to steal it.*

## The problem is three problems

1. **Local instantiation** (many guests/samples from one image): solved — read-only golden + per-guest qcow2 overlay, proven across all spikes. Linked clones are the same idea. Not the pain.
2. **Distribution of derived images** ("I changed one package; why am I shipping 12 GB?"): the real pain, addressed below with layering.
3. **Cold start at fleet scale** (a fresh instance needs 20 GB of goldens *now*): a different problem, addressed with lazy block access, not shipping formats.

## 1. Publication format: qcow2 backing chains as OCI layers (the 80% win)

A qcow2 with a backing file **is a delta layer**. Every derived image this project builds is already one (the vsockd golden is a few-MB overlay on the 600 MB noble base). So: publish images to the OCI registry (ORAS, already planned) as **manifests of qcow2 delta layers, each content-addressed, with the backing relationship pinned by digest in annotations**. Pull = fetch only missing layers; the puller materializes the chain in the local cache with *relative* backing paths (per the net-compile spike's backing-path lesson). This is Docker's model verbatim — manifest → content-addressed blobs → local CoW assembly — with qcow2 chains in place of overlayfs.

Disciplines that make it work:

- **Shallow chains** (2–3 deep: upstream base → org golden → task delta); every read miss walks the chain. Optional background flattening of hot images locally. This deliberately **inverts the handoff §7 guidance** ("publish flattened, chain locally"): publish *chained* for distribution economics; flatten *locally* if profiling demands.
- **Deltas derive only from pinned base digests**, enforced at push: a chain whose base drifted is corrupt by construction.
- Offline `virt-customize` derivation (already our practice) keeps task deltas naturally small; full Packer rebuilds are reserved for true bases.

## 2. Where lineage fails: content-defined chunking (targeted, not day one)

qcow2 deltas capture **write lineage, not content similarity**: a rebuilt Windows base (patch Tuesday) shares no chain with its predecessor, so the "delta" is everything. The fix for that case is CDC — `casync`/`desync`-style rolling-hash chunks, content-addressed chunk store (S3), ship only changed chunks; CDC finds the unchanged bulk of a rebuilt image with no lineage at all. It slots under the same registry index (chunk index as an OCI artifact). Hard constraint: CDC needs a **stable representation** — compressed qcow2 scrambles chunk boundaries; chunk the raw view or uncompressed qcow2, or the dedup evaporates. Prior art to study before building: **overlaybd** (block-level layered OCI with lazy pull — the closest existing system), KubeVirt containerDisk/CDI (cautionary: one layer = whole blob, no delta win), zchunk/zsync.

Position: hold CDC until base-rebuild churn actually hurts; monthly full-base ships may be acceptable long before task-delta ships are.

## 3. Cold start: materialize lazily, don't ship

- **Platform-native (EC2 production): EBS snapshots + Fast Snapshot Restore.** Bake the image cache as an EBS snapshot; instances attach a volume from it; EBS hydrates lazily from S3 and FSR removes the first-touch penalty. Zero bytes shipped by us at sample time; cache versioning = new snapshot. Elevates the handoff §6 one-liner to the designated production path.
- **Registry-only fallback (dev boxes, non-AWS): QEMU's curl block driver + copy-on-read.** An HTTPS URL can *be* a backing file; a local overlay opened `copy-on-read=on` self-populates with every block the guest reads. **Measured** ([lazy-pull spike](../spikes/lazy-pull/README.md)): lazy boot 10.2 s vs 9.8 s local — ~0.4 s penalty with zero pre-download; warm second boot 7.2 s with 11 MB residual fetch; and the mechanism resolves **multi-layer backing chains over HTTP**, so §1's chained distribution and lazy pull compose for free. Honest caveat: a small Linux golden's first boot over-fetched (123% of chain size — working set ≈ whole image, plus readahead/COR races), so for small images lazy pull wins on *time*, not bytes; the byte win arrives with large (Windows) goldens whose working set is a small fraction — measure then. Requires `qemu-block-extra` on Ubuntu. The shared-cache tier (one streamed copy serving many VMs on a host) uses the same chain plus `block-stream`/background flatten into a host cache layer — design sketch, not yet built.

## Recommendation

Local golden+overlay (done) → **chained-qcow2-over-ORAS** as the publication format (small to build; the compiler/image tooling already emits the deltas) → **EBS/FSR caches** in the EC2 deployment path → **curl+copy-on-read** as the registry-direct path where platform caches don't exist → CDC held as the targeted fix for base-rebuild churn.

The one-line answer to the Proxmox author: *linked clones are the overlayfs half; the missing half is content-addressed layer distribution, and qcow2 backing chains let you take it from Docker almost verbatim — and in the fleet case, EBS snapshots mean images may never be "shipped" at all.*
