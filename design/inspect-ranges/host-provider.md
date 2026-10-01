---
type: decision
title: "Deployment seam: sharded Inspect, local realization; the remote HostProvider path is deferred until sharding proves unviable"
status: accepted
tags: [inspect-ranges, sandbox, deployment, sharding, host-provider, decision]
timestamp: 2026-10-01
---

# Deployment seam: sharded Inspect, local realization; the remote HostProvider path is deferred until sharding proves unviable

*Decision record. `inspect_ranges` never creates the Nitro instance it runs on — it stipulates one ([agent-containment](agent-containment.md) precondition). This records how the stack reaches its instance in production, concretizing handoff §11's "separate where from what". An earlier same-day draft made a pluggable per-sample Docker-endpoint (`HostProvider`) the primary seam; superseded once Inspect's sharding emerged as the natural fit (and as how the run-inside-Nitro environment already operates).*

## Decision

**Sharding is the deployment model; `inspect_ranges` only ever realizes ranges against the local Docker daemon.**

- Inspect's sharding layer dispatches samples to instances; an Inspect worker runs on each instance and drives `inspect_ranges` in place. The "where" (instance provisioning, sample dispatch) belongs to the sharding layer and the caller's orchestration; the "what" (compose generation, range container, VM boot, vsock exec/file, evidence, teardown) is ours and is strictly host-local.
- Both deployment environments converge on the identical on-instance story. The orchestration environment's integration is: provision a Nitro instance its way (our bootstrap/AMI provides Docker + host prerequisites, gated by `inspect-ranges doctor --json`, fixable by `doctor --fix-script`) → run the worker on it. No inspect_ranges-specific provisioning interface to implement.
- **The remote path is not built**: no `HostProvider` interface, no remote-Docker-endpoint support, no `docker exec` stdio↔vsock bridge. The design sketch is retained below as the known-viable fallback, to be built only if sharding proves unviable.
- One cheap insurance policy in code: the vsock client sits behind a thin channel interface, so a bridged transport can be added later without touching anything above it. Nothing above the channel may know its transport.

## What we require from the sharding layer

The containment preconditions, restated as dispatch constraints:

- **At most one resident sample per instance at a time** — the entire [containment posture](agent-containment.md) is derived from this.
- The worker is told its isolation level (`instance` in production, `shared` on dev boxes) so the per-sample eval-log claim stays truthful; `shared` warns for untrusted-model evals.
- **Mid-run log/evidence sync off-instance**, not end-of-shard collection — prompt streaming is load-bearing for detection-over-prevention (agent-containment backlog item 2). This must be confirmed against Inspect's sharding semantics early; if sync is end-of-run only, evidence streaming needs its own channel.

## Development

- Linux workstations with KVM and the EC2 devbox run the same local path (dev *is* production topology, minus the isolation claim).
- Mac/laptop development uses VS Code Remote-SSH onto the devbox — already the documented path — so no remote Docker support is needed for dev either. (`DOCKER_HOST=ssh://` remoting is explicitly out: without the vsock bridge, exec against VMs cannot work remotely, and we are not building the bridge.)

## What "sharding proves unviable" means (triggers for building the fallback)

- The sharding layer cannot guarantee one resident sample per instance, and the isolation claim would have to be silently downgraded.
- It cannot provide mid-run log/evidence sync and a side channel is ruled out.
- An integrator genuinely cannot run a worker on the instance (policy or architecture) and must drive sandboxes from a central process.
- Warm-pool/cold-start economics demand per-sample host acquisition decisions that the sharding layer cannot express.

## The deferred fallback, for the record

A pluggable `HostProvider` returning a per-sample Docker endpoint, with the exec/file plane tunneled through one long-lived `docker exec` stdio↔vsock bridge per sample (setup ~45 ms once, then network RTT + the 1.1 ms vsock hop per call — see [the vsock-exec spike](../spikes/vsock-exec/README.md)). Interface sketch, so picking this up later starts from a design rather than a blank page:

```python
class RangeHost(Protocol):
    docker: DockerEndpoint        # DOCKER_HOST-style URL (unix:// | ssh:// | tcp+tls) + credentials
    isolation: Literal["instance", "shared"]   # claimed by the provider, logged per sample
    facts: HostFacts              # image cache path, CID allocation scope, arch

class HostProvider(Protocol):
    async def acquire(self, sample: SampleSpec) -> RangeHost: ...
    async def release(self, host: RangeHost) -> None: ...
```

Providers would register through the same entry-point mechanism as other inspect_ranges components; `acquire` gates on `doctor` readiness and fails the sample fast with the report. Everything above the channel abstraction is already transport-agnostic, so building this later is additive. If it is ever built for production use, the bridge gets the same conformance testing (`self_check`) as the fast path — not fallback status.
