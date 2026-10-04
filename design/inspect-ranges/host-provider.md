---
type: decision
title: "Deployment seam: two supported topologies — co-resident sharding, or a host interface separating the scaffold from the range"
status: accepted
tags: [inspect-ranges, sandbox, deployment, sharding, host-provider, decision]
timestamp: 2026-10-01
---

# Deployment seam: two supported topologies — co-resident sharding, or a host interface separating the scaffold from the range

*Decision record. `inspect_ranges` never creates the Nitro instance it runs on — it stipulates one ([agent-containment](agent-containment.md) precondition). This records how the stack reaches its instance in production, concretizing handoff §11's "separate where from what". An earlier same-day draft made a pluggable per-sample Docker-endpoint (`HostProvider`) the primary seam; superseded once Inspect's sharding emerged as the natural fit (and as how the run-inside-Nitro environment already operates).*

## Decision

**Sharding is the default deployment model; `inspect_ranges` realizes ranges against the Docker endpoint the deployment supplies** — the local daemon under sharding, or a `HostProvider`-supplied per-sample endpoint in the separated topology. Everything below the endpoint (compose generation, range container, VM boot, vsock exec/file, evidence, teardown) is identical in both.

- Inspect's sharding layer dispatches samples to instances; an Inspect worker runs on each instance and drives `inspect_ranges` in place. The "where" (instance provisioning, sample dispatch) belongs to the sharding layer and the caller's orchestration; the "what" (compose generation, range container, VM boot, vsock exec/file, evidence, teardown) is ours and is strictly host-local.
- Both deployment environments converge on the identical on-instance story. The orchestration environment's integration is: provision a Nitro instance its way (our bootstrap/AMI provides Docker + host prerequisites, gated by `inspect-ranges doctor --json`, fixable by `doctor --fix-script`) → run the worker on it. No inspect_ranges-specific provisioning interface to implement.
- **The host-interface path is fully supported** (revised 2026-10-03; it was previously deferred-until-sharding-proves-unviable): a `HostProvider` lets an orchestration layer allocate a machine per sandbox, with the Inspect scaffold running in a completely separate context from the range. **This topology has the stronger security posture**: in the co-resident topology the worker — and its model API credentials and live eval state — shares the instance an escaped agent would land on; the separated topology moves all of that outside the blast radius. Co-resident sharding remains the simpler default (direct vsock, no bridge); the host interface is preferred where isolation of the scaffold matters (e.g. frontier/untrusted-model runs).
- One cheap insurance policy in code: the vsock client sits behind a thin channel interface, so a bridged transport can be added later without touching anything above it. Nothing above the channel may know its transport.

## What we require from the sharding layer

The containment preconditions, restated as dispatch constraints:

- **One sample per instance lifetime** — the entire [containment posture](agent-containment.md) is derived from this, and "at a time" is not enough: under the threat model a compromised host can persist into the next sample even after every VM and container is removed. Release means the instance is destroyed or handed to an independently controlled reprovisioning process; a warm pool may hold only never-used instances, and a used instance never returns to one.
- The worker is told its isolation level (`instance` in production, `shared` on dev boxes) so the per-sample eval-log claim stays truthful; `shared` warns for untrusted-model evals.
- **Mid-run log/evidence sync off-instance**, not end-of-shard collection — prompt streaming is load-bearing for detection-over-prevention (agent-containment backlog item 2). This must be confirmed against Inspect's sharding semantics early; if sync is end-of-run only, evidence streaming needs its own channel.

## Development

- Linux workstations with KVM and the EC2 devbox run the same local path (dev *is* production topology, minus the isolation claim).
- Mac/laptop development uses VS Code Remote-SSH onto the devbox — already the documented path — so no remote Docker support is needed for dev either. (`DOCKER_HOST=ssh://` remoting is explicitly out: without the vsock bridge, exec against VMs cannot work remotely, and we are not building the bridge.)

## Choosing a topology

- **Co-resident (sharding)**: simplest; direct vsock fast path (1.1 ms exec); the worker's model credentials and eval state are on the instance — acceptable for dev and lower-stakes runs.
- **Separated (host interface)**: scaffold, credentials, and logs live outside the attackable instance; exec rides the `docker exec`↔vsock bridge (setup once per sample, then network RTT + ~1 ms per call). Preferred where the agent is genuinely untrusted.

## The host interface, as designed

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

Providers would register through the same entry-point mechanism as other inspect_ranges components; `acquire` gates on `doctor` readiness and fails the sample fast with the report. Everything above the channel abstraction is transport-agnostic, and the bridge is subject to the same conformance testing (`self_check`) as the local fast path.

The sketch is deliberately minimal; the production contract additionally needs (external review 2026-10-04, finding 10):

- **Lease semantics**: `acquire` returns a lease with an identity and an expiry; a sample that outlives its lease is reclaimed. Controller crashes, interrupted acquisition, partial boots, and network partitions are normal cases, not exceptions.
- **An independent reaper**: cleanup must be idempotent and recoverable from recorded resource ownership (instance tags, compose project names), never dependent on the original Python process reaching `finally`. The e2e spike demonstrated the failure concretely: `pkill` on the harness leaves the range running.
- **Release is destruction**: per the dispatch constraint above, `release` destroys the instance or hands it to independent reprovisioning; it never returns a used instance to a pool.
