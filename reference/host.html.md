# inspect_ranges.host – Inspect Ranges

The range-host extension point: a [HostBackendFactory](../reference/host.html.md#hostbackendfactory) named by `INSPECT_RANGES_HOST=<module>.<factory>[:<config>]` returns a [HostBackend](../reference/host.html.md#hostbackend) bundle, and the lease machinery and channel tier it builds on are public here. See [Implementing a Host Provider](../topology.html.md#implementing-a-host-provider) for the grammar, the registration walkthrough, and the contracts an implementation is held to.

## Registration

### HostBackendFactory

What a custom backend exports under the dotted path `INSPECT_RANGES_HOST` names. Must be cheap: no dialing, no probing; remote work belongs in the provider’s `acquire`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/backend.py#L87)

``` python
HostBackendFactory = Callable[[HostBackendContext], HostBackend]
```

### HostBackendContext

What a [HostBackendFactory](../reference/host.html.md#hostbackendfactory) is called with.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/backend.py#L44)

``` python
@dataclass(frozen=True)
class HostBackendContext
```

#### Attributes

`origin` str  
The full `INSPECT_RANGES_HOST` value, verbatim. The backend’s provider MUST stamp it as each lease’s `origin` (`LeaseStore.acquire(origin=...)`), so a fresh process can re-resolve teardown from disk alone; extra placement data rides inside the config portion of the value.

`config` str \| None  
The text after the value’s first colon, `None` when absent: the backend’s own opaque config.

`state_dir` Path  
The shared state dir (`leases.json` and the CID registry live here); hand it to [LeaseStore](../reference/host.html.md#leasestore) to reuse the lease machinery.

### HostBackend

One resolved backend bundle: the provider plus the hooks a [HostProvider](../reference/host.html.md#hostprovider) alone cannot carry.

`channel_for_lease` is `None` for a co-resident backend (the runtime keeps its local `up`/`down`/channel seams); a separated backend supplies it and the runtime derives the swapped seams from it (`seams.py`). `reclaim` overrides the reaper’s teardown-by-origin connector; left `None`, a separated backend gets the channel-teardown default and a co-resident one the reaper’s direct `down`. `doctor_probe` lets `inspect-ranges doctor` check reachability.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/backend.py#L56)

``` python
@dataclass(frozen=True)
class HostBackend
```

#### Attributes

`separated` bool  
Whether the backend reaches its host through a channel rather than running co-resident.

#### Methods

reclaimer  
The teardown-by-origin connector the reaper runs: the explicit `reclaim`, the channel-teardown default for a separated backend, or `None` for a co-resident one (the reaper’s direct `down` applies).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/backend.py#L73)

``` python
def reclaimer(self) -> ReclaimFn | None
```

### ChannelForLease

A control channel to the (possibly remote) host a lease names: the one hook a separated backend supplies, from which the runtime derives every other seam it needs. A typical implementation wraps the backend’s own [Transport](../reference/host.html.md#transport) in a [MessageChannel](../reference/host.html.md#messagechannel), inheriting the whole wire discipline (request ids, retries, budgets, validation).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/seams.py#L32)

``` python
ChannelForLease = Callable[[HostLease], MessageChannel]
```

### ReclaimFn

The reaper’s teardown-by-origin connector: `(lease, state_dir)`; raises on failure, after which the lease stays `reaping` and the next sweep retries.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/backend.py#L19)

``` python
ReclaimFn = Callable[[HostLease, Path], None]
```

### DoctorProbe

An optional reachability probe for `inspect-ranges doctor`: `None` when healthy, else the failure detail.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/backend.py#L22)

``` python
DoctorProbe = Callable[[], str | None]
```

## Provider Seam

### HostProvider

Acquires and releases range hosts.

`acquire` returns a lease (identity plus expiry; a sample that outlives its lease is reclaimed by the independent reaper), gates on doctor readiness, logs the isolation claim, and starts renewal. `release` is destruction and must only follow a successful teardown: a used host is never returned to a pool, and a failed teardown frees nothing. `abandon` is the deliberate keep-it-running path (`cleanup=False`): renewal stops but the lease stays, so the reaper reclaims after expiry.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L87)

``` python
class HostProvider(Protocol)
```

### RangeHost

One acquired range host: the channel to it, and what the deployment claims about it.

`channel` is `None` between acquire and boot in the co-resident backend (the local path builds its channel from booted guest CIDs, after `up`); the separated backend attaches it at acquire. Consumers that need the channel assert its presence at their boundary.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L71)

``` python
class RangeHost(Protocol)
```

#### Methods

check_lease  
Raise [LeaseLostError](../reference/host.html.md#leaselosterror) when this host’s lease has been lost (reaped, or expired and reclaimed); ops call this first, so lease loss fails the sample loudly at its next operation instead of silently running on a reclaimed host.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L82)

``` python
def check_lease(self) -> None
```

### SampleSpec

What a `HostProvider.acquire` needs to know about the sample it hosts.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L18)

``` python
class SampleSpec(BaseModel)
```

#### Attributes

`bundle_digest` Sha256Hex  
The canonical bundle digest: sha256 of the rendered bundle’s `manifest.json` bytes.

### LeasePlacement

Driver-side placement facts the lease record needs so the reaper can act from disk alone.

[SampleSpec](../reference/host.html.md#samplespec) deliberately carries none of these (they are placement, not sample identity), yet the recorded lease shape requires them; `acquire` takes them as a second argument. Recorded in the `range-host-v1.md` ledger as a seam-signature extension over the `host-provider.md:83-91` sketch.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L56)

``` python
class LeasePlacement(BaseModel)
```

#### Attributes

`evidence_location` str \| None  
The per-sample evidence prefix the host’s capture writer targets (`None` when evidence is off). Driver-derived (`evidence-v1.md`: the driver computes the location and hands the host a put-scoped destination at acquire); lands on the lease so the applier and the reaper act from disk alone.

### HostCapabilities

What the deployment declares it can do; absence refuses at planning, never degrades silently.

v1 pins every capability to its only supported value: image delivery is pre-seeded (the cache already holds the verified chain), and neither `forward` upstream reach nor egress grants exist yet.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L31)

``` python
class HostCapabilities(BaseModel)
```

#### Attributes

`evidence_sink` Literal\['location'\]  
How the host delivers capture evidence (`host-provider.md:104`): it writes to the per-sample location the driver hands it at acquire (`LeasePlacement.evidence_location`), through a put-only credential. The only v1 mode; a host that cannot write evidence would refuse at planning, never degrade silently.

### HostFacts

Host-class identity: render inputs are host-class declarations, never per-instance probes.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L46)

``` python
class HostFacts(BaseModel)
```

### IsolationLevel

The per-sample isolation claim, logged so the eval-log claim stays truthful (`host-provider.md:27`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/host.py#L14)

``` python
IsolationLevel = Literal["instance", "shared"]
```

## Leases

### HostLease

One sample’s claim on a host: identity plus absolute expiry, the exact record shape from `range-host-v1.md`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L58)

``` python
class HostLease(BaseModel)
```

#### Attributes

`lease_id` str  
Opaque lease identity (uuid4 hex).

`origin` str  
The backend that minted the lease: `local`, or `uds:<socket>` for the applier path.

`expires_at` str  
Absolute ISO-8601 UTC expiry; the reaper compares against it, never against liveness.

`evidence_location` str \| None  
The sample’s evidence prefix (`evidence-v1.md`), when evidence is on: the applier writes capture streams there, and the reaper reap-seals an abandoned record there. Additive over the recorded `range-host-v1.md` shape (old entries parse with `None`).

### LeaseStore

Cross-process host leases over a flock-guarded `leases.json`, keyed by lease id.

Shares the `JsonRegistry` discipline with the CID allocator: atomic sorted writes, and entries another version wrote are preserved verbatim, never silently dropped.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L93)

``` python
class LeaseStore
```

#### Methods

acquire  
Mint a fresh active lease expiring `ttl_s` (default [lease_ttl_s()](../reference/host.html.md#lease_ttl_s)) from now.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L105)

``` python
def acquire(
    self,
    *,
    project: str,
    task_name: str,
    sample_id: str,
    isolation: IsolationLevel,
    origin: str,
    bundle_path: str,
    bundle_digest: str,
    staging: str,
    host_facts: HostFacts,
    ttl_s: float | None = None,
    evidence_location: str | None = None,
) -> HostLease
```

`project` str  

`task_name` str  

`sample_id` str  

`isolation` [IsolationLevel](../reference/host.html.md#isolationlevel)  

`origin` str  

`bundle_path` str  

`bundle_digest` str  

`staging` str  

`host_facts` [HostFacts](../reference/host.html.md#hostfacts)  

`ttl_s` float \| None  

`evidence_location` str \| None  

renew  
The renewal CAS: extend expiry if and only if the lease still exists and is `active`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L143)

``` python
def renew(self, lease_id: str, ttl_s: float | None = None) -> HostLease
```

`lease_id` str  

`ttl_s` float \| None  

release  
Remove the lease; idempotent, callable from any process. Release is destruction: call only after a successful teardown.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L165)

``` python
def release(self, lease_id: str) -> None
```

`lease_id` str  

leases  
Every parseable lease, sorted by lease id (read-only; never rewrites the file).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L174)

``` python
def leases(self) -> list[HostLease]
```

expired  
Leases past expiry or already `reaping`, without mutating anything (the doctor-hint view of what a sweep would select).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L179)

``` python
def expired(self) -> list[HostLease]
```

mark_reaping  
One sweep selection under the flock: every lease already `reaping` (crash resume) plus every `active` lease whose expiry, re-checked against now, has passed (a renewal may have landed since the sweep was scheduled), marked `reaping`. Teardown happens outside the lock; a marked lease refuses renewal, so the race is settled here, atomically, in one direction or the other.

A sweep that selects nothing never rewrites the file (an idle `--interval` reaper must not churn `leases.json`), so candidates are probed read-only first and the marking write re-checks under its own lock.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L188)

``` python
def mark_reaping(self) -> list[HostLease]
```

### LeaseLostError

The sample’s host lease is gone or being reaped; the sample fails loudly as lease loss, never limps on.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L54)

``` python
class LeaseLostError(RuntimeError)
```

### lease_ttl_s

`INSPECT_RANGES_LEASE_TTL_S` as a positive float, default 600; renewal runs at a third of it.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/leases.py#L32)

``` python
def lease_ttl_s() -> float
```

### LocalRangeHost

One leased co-resident host. The channel is attached by the provider after boot (today’s path builds it from booted guest CIDs), so it is `None` until then.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/local.py#L45)

``` python
class LocalRangeHost
```

#### Methods

check_lease  
Raise the [LeaseLostError](../reference/host.html.md#leaselosterror) a renewal step recorded, so lease loss fails the sample loudly at its next operation.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/local.py#L60)

``` python
def check_lease(self) -> None
```

renew_now  
One renewal step, exactly what the background task runs at TTL/3; the renewal-versus-reap tests drive it directly.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/local.py#L69)

``` python
async def renew_now(self) -> None
```

### local_host_facts

This machine’s host-class identity; `INSPECT_RANGES_HOST_CLASS` names the class (declarations, never per-instance probes).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_host/local.py#L36)

``` python
def local_host_facts() -> HostFacts
```

## Channel

### RangeChannel

Transport-agnostic control plane to one sample’s range (`host-provider.md`).

Implementations: [MessageChannel](../reference/host.html.md#messagechannel) over a real or mock transport. Nothing above this interface may know which transport carries it.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L198)

``` python
class RangeChannel(Protocol)
```

### MessageChannel

[RangeChannel](../reference/host.html.md#rangechannel) implementation over any per-operation-connect [Transport](../reference/host.html.md#transport).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L244)

``` python
class MessageChannel
```

#### Methods

trace_tail  
The most recent codec trace events, formatted one per line.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L266)

``` python
def trace_tail(self, limit: int = 40) -> list[str]
```

`limit` int  

ping  
Liveness and protocol-version probe for one guest.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L575)

``` python
async def ping(self, guest: str) -> PongReply
```

`guest` str  

session  
The guest daemon’s current session id, via a fresh ping.

The provider pins it per guest at boot and treats a later change as a daemon restart: the wire layer’s exactly-once guarantee (dedupe, tombstones, durable replies) holds only within one session (`SessionHex`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L581)

``` python
async def session(self, guest: str) -> str
```

`guest` str  

exec  
Run `request` in the guest; `stdin` must match the request’s `data_size` declaration. `bulk_cap` bounds the accepted reply bulk (stdout plus stderr), reader-side.

Liveness-polled: the initial reply wait is capped so at least one poll precedes the exec deadline; `pending` replies prove liveness while the command runs, so long execs stay allowance-bounded between polls, and three consecutive allowance windows with zero liveness evidence are a channel-layer failure. The exec deadline (`command_ms` plus the shared observation grace, or the untimed total) firing without RECENT liveness is a channel-layer verdict; with recent liveness it is a command-layer verdict (the guest demonstrably failed to kill within its own grace).

At-most-once: a resend is only legal while the request provably never left (connect failed); once delivery is possible, a daemon `ENOENT`/`ESTALE` for the id surfaces as `TransportFailure`, never a re-run.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L588)

``` python
async def exec(
    self,
    guest: str,
    request: ExecRequest,
    *,
    stdin: bytes | None = None,
    bulk_cap: int = 2 * DEFAULT_BULK_CAP,
) -> ExecOutcome
```

`guest` str  

`request` [ExecRequest](../reference/host.html.md#execrequest)  

`stdin` bytes \| None  

`bulk_cap` int  

read_file  
Read a guest file, capped at `cap` bytes.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L830)

``` python
async def read_file(
    self, guest: str, path: str, *, cap: int = DEFAULT_BULK_CAP
) -> bytes
```

`guest` str  

`path` str  

`cap` int  

write_file  
Write `data` to a guest file (exactly once per request id, even across retries).

`mode` sets the created file’s permission bits atomically with the write (`WriteFileRequest.mode`); `None` keeps the daemon default.

Returns the delivery-attempt count: above 1 means a same-id resend happened (the provider’s session-invalidation policy reads this for side-effecting operations).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L848)

``` python
async def write_file(
    self, guest: str, path: str, data: bytes, *, mode: int | None = None
) -> int
```

`guest` str  

`path` str  

`data` bytes  

`mode` int \| None  

forward  
Open a capability-gated forward (not implemented until the realizer integration).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L874)

``` python
async def forward(self, guest: str, host: str, port: int) -> ForwardReply
```

`guest` str  

`host` str  

`port` int  

diag  
Read the daemon’s diagnostics: the in-guest ring buffer tail plus the supervised listener-restart count.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L881)

``` python
async def diag(self, guest: str, *, max_entries: int = 100) -> DiagReply
```

`guest` str  

`max_entries` int  

exec_events  
Read the daemon’s exec-witness ring from `since_seq` (execve-witness-v1); the FIRST call arms the in-guest subscriber (lazy-arm).

A daemon without the witness answers a typed error that surfaces as `GuestError` (`ENOSYS` from a Linux daemon whose kernel lacks the process connector; `EPROTO` from the Windows daemon’s unknown-kind fallback): the caller records a declared capability drop, never a failure.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L887)

``` python
async def exec_events(
    self, guest: str, *, since_seq: int = 0, max_events: int = 128
) -> ExecEventsReply
```

`guest` str  

`since_seq` int  

`max_events` int  

heartbeat  
Poll the applier for uptime and per-guest state (the driver-initiated heartbeat verb).

The seam’s “periodic heartbeat” (`host-provider.md`) is driver-polled: a pull verb fits per-operation-connect and connectionless transports where an unsolicited push does not. The poll reuses the existing `PingRequest` to the host endpoint and expects the existing [Heartbeat](../reference/host.html.md#heartbeat) reply with the matching id, so no wire kind was added; a dedicated `HeartbeatRequest` kind is the recorded multi-host growth path (`range-host-v1.md`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L902)

``` python
async def heartbeat(self) -> Heartbeat
```

realize  
Stream stage reports until `ready` or `failed`.

Hardened per the realize policy: every transport interaction (connect, send, each report read, the terminal drain, close) sits inside the layered budgets (per-report channel allowance, untimed outer total); reports are capped in count and must follow strictly increasing stage order; an early stream end is loss and is resumed by resending the same request id (the applier deduplicates and replays; already-yielded reports must replay identically); anything else is tamper.

`gap_allowances` widens the per-report allowance per gap, keyed by the stage the gap follows (`None` keys the gap before the first report). The applier legally emits nothing while a gap’s occupant runs (the first-use range-image build before any report, `compose up --wait` after `construct`, the guest-boot exec after `boot`, the sequential readiness pass after `verify`), so the caller supplies each occupied gap’s plan-derived envelope; the channel allowance stays the floor, every unlisted gap keeps it, and each gap stays bounded (a wedged occupant still fails at its envelope, not at the untimed total) (quality-review A10, extended to the sibling gaps by R2-3).

Stage-order leniency, deliberate: skipping stages is allowed (a cache-hitting applier legitimately jumps ahead) and `failed` is allowed anywhere including first (an honest fast failure); only `ready` as the very first report is tamper. A hostile applier can emit the honest sequence anyway, so tightening buys no security.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L911)

``` python
async def realize(
    self,
    bundle_digest: Sha256Hex,
    grants: Sequence[str],
    *,
    gap_allowances: Mapping[str | None, float] | None = None,
) -> AsyncIterator[StageReport]
```

`bundle_digest` Sha256Hex  

`grants` Sequence\[str\]  

`gap_allowances` Mapping\[str \| None, float\] \| None  

teardown  
Tear the range down. Teardown is contractually idempotent: callers may retry with a fresh id.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L1116)

``` python
async def teardown(self) -> None
```

### Transport

Per-operation connection factory; `endpoint` is a guest name or `HOST_APPLIER`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L192)

``` python
class Transport(Protocol)
```

### ByteStream

One connection’s byte stream; `receive` returns empty bytes at EOF.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L184)

``` python
class ByteStream(Protocol)
```

### ExecRequest

Run an argv command in the guest (never an implicit shell); stdin rides the bulk.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/protocol.py#L142)

``` python
class ExecRequest(_BulkMessage)
```

#### Attributes

`data_size` int \| None  
Byte count of the out-of-band bulk that follows the control frame; `None` means no bulk frames at all.

### ExecOutcome

Validated exec result with the bulk split back into streams.

`attempts` counts deliveries of the exec request itself (not liveness polls): a value above 1 means a same-id resend happened, which the provider’s session-invalidation policy uses to decide whether exactly-once still holds for side-effecting operations.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/channel.py#L167)

``` python
@dataclass
class ExecOutcome
```

#### Attributes

`rc` int  
Signed exit status (killed-by-signal is negative, `-signal`).

`stdout_truncated` bool  
Whether stdout was cut at the guest’s output cap (`SUBMIT`-style line protocols must treat truncation as failure).

### StageReport

Staged realization progress; `failed` carries diagnostics in `detail`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/protocol.py#L438)

``` python
class StageReport(_MessageBase)
```

### ForwardReply

Reply to a granted `forward`; `handle` names the opened forward (capability-gated, wire-stable ahead of its implementation).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/protocol.py#L300)

``` python
class ForwardReply(_MessageBase)
```

### PongReply

Reply to `ping`: the daemon’s identity string, protocol version, and boot session.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/protocol.py#L240)

``` python
class PongReply(_MessageBase)
```

#### Attributes

`session` SessionHex  
Required: an honest daemon always reports its session (provider-v1 layer 2b).

### DiagReply

Reply to `diag`: the tail of the daemon’s in-guest diagnostic ring buffer.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/protocol.py#L315)

``` python
class DiagReply(_MessageBase)
```

#### Attributes

`listener_restarts` int  
Supervised listener recreations since daemon start: the storm battery asserts it stays 0.

### Heartbeat

The host’s heartbeat reply, driver-polled (a pull verb fits per-operation-connect transports): uptime plus per-guest state.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/bc7b698e4543ca9c7c111f9ab75fdd349568bf28/src/inspect_ranges/_channel/protocol.py#L447)

``` python
class Heartbeat(_MessageBase)
```
