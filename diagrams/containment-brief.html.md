# containment-brief – Inspect Ranges

## What this is

The layered-architecture diagram for the overview’s Range Container section (also serving the Security Model section). The prose describes four nesting levels plus a sideband channel entirely in words; this diagram is that structure drawn once.

The one idea it must land: *everything in the range lives as VMs inside one unprivileged container on a dedicated instance; the only way in or out is a hypervisor channel that is not a network, plus evidence streaming off-instance.*

## Structure (fixed)

Nested boxes, outermost to innermost:

1.  **EC2 Nitro instance** — annotated `one sample per instance` (the inter-sample boundary).
2.  **The sandbox-control port** — a small violet box straddling the instance’s top edge, labeled `sandbox control`. This is the fixed on-instance endpoint of the control channel; the diagram is deliberately silent about who drives it (a co-resident Inspect worker, or a remote scaffold via the host interface), so it stays true in both deployment topologies. Do not put “docker” in the port label: `docker exec` is only the bridging transport in the separated topology, and Docker is never the control plane.
3.  **Range container** — annotated `unprivileged · libvirtd + QEMU`. Inside it:
    - A row of VMs: `router VM` (gray), `web VM` and `db VM` (blue targets), `agent VM` (red, rightmost). Each VM carries a small violet notch on its top edge — the same port motif as the sandbox-control box — saying every guest is addressable over vsock (setup and scoring reach targets this way) without drawing a fan of lines (tried and rejected: the diagonals strike through the header text) or a shared rail (rejected: vsock is host↔︎guest point-to-point, and a bus visual would imply guests can reach each other over it).
    - A strip below them: `Linux bridges + generated nftables`, annotated as existing only in the container’s netns. Every VM connects down to it with a short plain line (the agent has a real NIC like everyone else).
4.  Two channels that cross boundaries, one per corner — control in at the top right, evidence out at the bottom right:
    - A violet arrow from the port straight down into the `agent VM`, passing through the container border — the virtio-vsock control channel, labeled `not a network`. It must visibly bypass the bridges.
    - An amber arrow leaving the instance, labeled evidence streaming off-instance (pcaps, consoles).

- A muted note inside the container: `egress: none` — nothing outside the range is reachable from inside it.

## Style

House style: clean lines, soft solid fills, generous whitespace. Indigo = trusted harness, violet = control plane, amber = evidence, red = attacker, blue = targets, gray = infrastructure. Monospace for things that are configuration or commands, sans-serif for component names. Light theme, ~700 px content column.

## Open

Proportions, label placement, how the vsock arrow crosses the container border legibly. Structure and color semantics are fixed.
