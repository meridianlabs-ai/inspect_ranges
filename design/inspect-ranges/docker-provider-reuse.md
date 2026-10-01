---
type: decision
title: Own the libvirt sandbox provider; port selected pieces of Inspect's Docker provider
status: accepted
tags: [inspect-ranges, sandbox, docker, decision]
timestamp: 2026-09-30
---

# Own the libvirt sandbox provider; port selected pieces of Inspect's Docker provider

*Decision record. The `inspect_ranges/libvirt` sandbox uses Docker to host both the agent's `default` container and the `range` container (libvirtd + QEMU) — see [the design handoff §4](../inspect_ranges_handoff.md). This records whether that provider should reuse Inspect's built-in Docker sandbox provider, and what we give up by not doing so. Surveyed against `inspect_ai` 0.3.272 (`inspect_ai/util/_sandbox/docker/`).*

## Decision

We write our own sandbox provider rather than subclassing or delegating to Inspect's `DockerSandboxEnvironment`. We **port (copy with attribution)** the small set of Docker-provider pieces that encode hard-won operational fixes, and write the rest ourselves.

Inspect is MIT-licensed, so copying with attribution is permitted. The Docker provider is currently stable, so the cost of not tracking upstream changes automatically is low.

## Why

- **We need to control the startup sequence.** Our sample startup is not "`compose up` and wait until healthy": the veth attach must happen after the containers exist but before the range is declared ready, and readiness must cover VM boot (minutes for Windows DCs under nested virtualization). The Docker provider fuses start and wait-for-healthy into one step, so reusing it would mean working around it.
- **Most of our provider has no Docker equivalent anyway.** VM environments (`sandbox("dc01")`) exec through the QEMU guest agent via the range container; per-range event logs, evidence collection, and cleanup of VM overlays and veth pairs are ours regardless. Only the agent container's exec path overlaps meaningfully.
- **No dependence on private APIs.** Everything Docker-specific in Inspect is private (`inspect_ai.util._sandbox.docker`, including `ComposeProject`, the `compose_*` helpers, the cleanup registry, and provider lookup by name). Porting specific functions avoids importing any of it and lets us reshape them — e.g. one shared "exec into a container" core used for both the agent container and the range container.

## What we give up, and how we handle it

Roughly 600–900 of the provider's ~2,400 lines matter to us. The value is in subtle behavior, not volume:

| Piece (upstream location) | What it provides | Our approach |
|---|---|---|
| Agent-container `exec` (`docker.py`) | In-container `/usr/bin/timeout -k` so timeouts actually kill the process tree (`docker exec` doesn't forward signals); timeout vs OOM-kill disambiguation from exit codes 124/137/143 plus elapsed time; partial output preserved on timeout; output limits; env passed via `docker exec --env` and wrappers invoked by absolute path, as the `SandboxEnvironment.exec` contract requires | **Port.** This is the hottest path — every agent tool call. |
| Failure classification (`failure.py`, `diagnostics.py`) | Distinguishes "the sandbox is dead" (`SandboxUnavailableError`) from "your command failed", with deliberately narrow matching; logs a one-time post-mortem for a dead container | **Port.** |
| `write_file` / `read_file` (`docker.py`) | Parent-directory creation, binary via base64, staged `compose cp` with canary and symlink/escape validation, size limits, mapping to `FileNotFoundError` / `PermissionError` / `IsADirectoryError` | **Port.** These are exactly what Inspect's sandbox `self_check` exercises. |
| Docker CLI resilience (`compose.py` `compose_command`) | Retries hung commands (observed ~1/1000 on EC2 under load) and CLI processes that exit before reading stdin; caps concurrent Docker CLI invocations | **Port.** Our production environment is exactly where these hangs were observed. |
| Lifecycle and cleanup (`cleanup.py`) | Per-batch registry of running projects, timeouts around `compose down`, the "left running" table under `--no-sandbox-cleanup`, `inspect sandbox cleanup <provider>`, orphaned-file cleanup | **Rewrite**, modelled on upstream. Ours must also tear down VM overlays and veth pairs and support attaching to kept-alive failed ranges. |
| `connection()`, version prereqs, image pull / prebuilt checks | `docker exec -it` / VS Code attach, Docker and Compose version checks, `pull --policy missing`, prebuilt-image verification | **Rewrite** as needed; small. |

Not needed at all (they exist because users author compose files; ours are generated from `range.yaml`): compose/Dockerfile auto-discovery, building user Dockerfiles, sample-metadata interpolation into compose variables, Inspect's internal images, `ComposeConfig` auto-compose file management, and the `x-default` / `container_name` rules.

## Guardrails

- Keep ported code in one clearly marked module, with a header naming the upstream file(s) and the `inspect_ai` version they came from.
- Run Inspect's sandbox conformance suite (`self_check`) against our agent container in CI from day one ([handoff §10](../inspect_ranges_handoff.md)). It verifies the exec/read/write behavior we ported.
- Occasionally diff the ported functions against upstream; cheap while the provider is stable.

## Revision 2026-10-01: always-`kind: vm` narrows the ported surface

The [agent-containment decision](agent-containment.md) (after the [vsock-exec spike](../spikes/vsock-exec/README.md)) makes the agent a VM, so there is no agent container and no `docker exec` hot path. This changes the table above:

- **Agent-container `exec` and `write_file`/`read_file`: no longer ported.** The agent and the target VMs share one exec/file mechanism — the vsock daemon. The upstream code's *behavioral contract* still guides the daemon's design (timeout kills the process tree, timeout-vs-OOM disambiguation, partial output on timeout, output limits, the exception mapping `self_check` exercises), but as a specification, not copied code.
- **Failure classification: adapt the idea, not the code.** "Sandbox dead vs command failed" with narrow matching remains the model; the signals are now VM/vsock-health ones, not Docker ones.
- **Docker CLI resilience (`compose_command`): still ported.** We drive compose for the range container; the hang/retry/concurrency fixes apply unchanged.
- **Lifecycle and cleanup: still rewritten** modelled on upstream (now also covering VM overlays and kept-alive failed ranges; veth pairs are gone from the cleanup story).
- Inspect's `self_check` conformance suite now runs against the vsock exec path in CI — it is the acceptance test for the daemon replacing the ported exec code.

## Revisit if

- Inspect exposes a public, supported Docker-exec building block that we could depend on instead of porting.
- The upstream provider changes substantially in the areas we ported (e.g. new exec or failure-classification fixes).
- A `kind: container` agent is ever introduced as an optimization — the exec/file porting rows above come back into scope.
