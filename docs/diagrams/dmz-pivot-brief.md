# Design brief: the dmz-pivot topology diagram

## What this is

The network topology for the `dmz-pivot` example range, placed directly beside (or under) the `range.yaml` listing in the overview's Range Definition section. Readers parse the YAML by mentally drawing this picture; the diagram closes that loop and anchors every later reference to the example (challenges, compilation, scoring).

The one idea it must land: *the YAML on the left is this network — two isolated segments joined only by a router whose ACL admits a single port.*

## Structure (fixed)

- Two segment containers side by side: `dmz · 10.80.10.0/24` on the left, `internal · 10.80.20.0/24` on the right. Soft gray, dashed border (they are broadcast domains, not devices).
- In the DMZ: the `attacker` VM (red — the untrusted principal, annotated `entry: external`) and the `web` host (blue, `10.80.10.10`).
- In internal: the `db` host (blue, address allocated by IPAM, shown as `10.80.20.x`).
- The `router` (gray — infrastructure) sits in the gap between the segments, joined to each by a plain connector, with its two interface addresses shown.
- The ACL annotation under the router, monospace: `acl: dmz → internal · tcp/5432 only`. This is the diagram's payload; it must read clearly.

## Style

House style from the sibling projects: clean lines (roughness 0), soft solid fills, generous whitespace, monospace for addresses/CIDRs/ACL text, sans-serif for names. Blue = target hosts, red = attacker, gray = infrastructure and containers. Light theme, white page, ~700 px content column.

## Open

Proportions, spacing, exact label placement. The structure and wording above are fixed.
