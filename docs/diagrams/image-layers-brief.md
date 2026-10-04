# Design brief: the image-layers diagram

## What this is

The layer-cake diagram for the overview's Images section, placed after the bullet list that explains sharing. The prose circles the idea in three bullets; the diagram shows it once.

The one idea it must land: *a full image is never copied — the base ships once, a golden layer adds megabytes, and each VM gets only a tiny private copy-on-write overlay that dies with the range.*

## Structure (fixed)

A stack, widest at the bottom (shared) and narrowing upward (private):

1. **Upstream base image** — the widest bar at the bottom (gray — not ours), e.g. `ubuntu-24.04` cloud image.
2. **Golden additions** — a narrower bar sitting directly on it (indigo — our layer): the control daemon and settings, applied without booting.
3. **Per-VM overlays** — small boxes fanning out above, one per guest (`web`, `db` blue; `agent` red), each joined to the golden layer by a plain connector.

Captions carry the lifecycle semantics, monospace and muted:

- Above the overlay row: created instantly, copy-on-write, deleted with the range.
- Below the base: the bottom two tiers are shared, read-only, published as layers and fetched only if a host doesn't already have them.

## Style

House style and palette as the sibling diagrams: clean lines, soft solid fills, generous whitespace, monospace for lifecycle/config facts, sans-serif for layer names. Light theme, ~700 px content column.

## Open

Proportions, caption placement. Structure, color semantics, and the shared-vs-private reading (width = how widely shared) are fixed.
