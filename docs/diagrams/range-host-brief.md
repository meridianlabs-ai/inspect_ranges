# range-host diagram brief

**Audience/context:** `design/ranges-overview.qmd`, the new Range Host section. Shows the deployment seam between the Inspect scaffold and the range host: what crosses it, in which direction, and what never crosses it.

**The one idea:** the seam is three flows across a trust boundary — a realization bundle in, a control channel in both directions, evidence out — and the model credentials never cross.

## Composition

- **Left: "Inspect scaffold" panel** (HARNESS indigo tint). Three inner boxes: "compile + render" (source of the bundle), "agent loop" (drives the channel), "model credentials" (deliberately flow-less: nothing connects to it, which is the point). Below the panel, a separate **"evidence store · append-only"** box (amber stroke): evidence is durable storage the scaffold cannot rewrite, so it is *not* inside the scaffold panel.
- **Right: "range host" panel** (white, heavy gray border, echoing the Nitro instance in the containment diagram) with the caption "one sample per instance". Inside: the **applier** (receives the bundle) above the **range container** holding three VM chips (router gray, target blue, agent red), each with the violet vsock notch from the containment diagram.
- **Trust boundary**: a vertical dashed muted line in the gap between the panels, labeled "trust boundary" above it. All flow labels end left of the line so text never collides with it.
- **Three flows crossing the gap** (labels above their arrows, right-aligned to a common edge):
  - "realization bundle" → (gray), compile + render → applier.
  - "control channel" ↔ (CONTROL violet, both arrowheads), agent loop ↔ range container, with the guest-control verbs ("exec() · read_file() / write_file() · forward()", small mono) under the arrow — the diagram carries the interface on its own, so the overview section needs no Python block. Violet deliberately matches the containment diagram's sandbox-control port and vsock notches, so the port and the channel read as the same thing.
  - "evidence" ← (EVIDENCE amber), range host → evidence store, matching the containment diagram's amber evidence arrow.

## Deliberate silences

- **The transport is unnamed.** No "docker", no "ssh", no "queue": the seam contract is transport-agnostic (direct vsock when co-resident, bridged or queued messages when separated), and the diagram must not take sides — same rule as the containment diagram's "sandbox control" port label.
- **No internals of either side** beyond what the flows need: no vsock daemons, no bridges, no compiler stages. The containment diagram owns the inside of the instance.

## Size

~640 px wide, within the 5.83" Word column budget (keep ≲705 px so type stays legible beside the other diagrams).
