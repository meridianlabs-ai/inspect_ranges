# inspect_ranges.attackbox – Inspect Ranges

The attack-box extension point: an [AttackBoxFactory](../reference/attackbox.html.md#attackboxfactory) named by `INSPECT_RANGES_ATTACK_BOX=<module>.<factory>[:<config>]` returns an [AttackBoxBackend](../reference/attackbox.html.md#attackboxbackend) bundle, and the foothold attachment and resolution machinery it builds on are public here. The provider boots a range’s dedicated attack box from a [FootholdAttachment](../reference/attackbox.html.md#footholdattachment) and returns an [AttackBoxHandle](../reference/attackbox.html.md#attackboxhandle) whose `exec_endpoint` serves the daemon wire protocol.

See [Registering a Provider](../attackbox.html.md#registering-a-provider) for the grammar and the registration walkthrough, and [Provider Contract](../attackbox.html.md#provider-contract) for the proof obligations an implementation is held to.

## Registration

### AttackBoxFactory

What the dotted path in `INSPECT_RANGES_ATTACK_BOX` names. Must be cheap: no dialing, no probing; remote work belongs in the provider’s `boot`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L140)

``` python
AttackBoxFactory = Callable[[AttackBoxContext], AttackBoxBackend]
```

### AttackBoxContext

What an [AttackBoxFactory](../reference/attackbox.html.md#attackboxfactory) is called with.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L128)

``` python
@dataclass(frozen=True)
class AttackBoxContext
```

#### Attributes

`origin` str  
The full `INSPECT_RANGES_ATTACK_BOX` value, verbatim: what `up` stamps into the attack-box record, so a fresh process re-resolves teardown from disk alone.

`config` str \| None  
The text after the value’s first colon, `None` when absent: the backend’s own opaque config.

`state_dir` Path  
The shared project state dir (the attack-box record lives under it).

### AttackBoxBackend

One resolved backend bundle: the provider plus the hooks the provider protocol alone cannot carry.

`reclaim` overrides the teardown-by-origin connector; left `None`, teardown runs `provider.teardown` with the recorded token. `doctor_probe` lets `inspect-ranges doctor` check reachability. `capabilities` is the declared-drop surface the evidence record and the conformance battery hold the provider to.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L104)

``` python
@dataclass(frozen=True)
class AttackBoxBackend
```

#### Methods

reclaimer  
The teardown-by-origin connector `down` runs: the explicit `reclaim`, or the provider’s own `teardown` with the recorded token.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L116)

``` python
def reclaimer(self) -> AttackBoxReclaimFn
```

### AttackBoxReclaimFn

The teardown-by-origin connector: `(record, state_dir)`; raises on failure, after which `down` refuses to touch the range’s own resources (a dead netns strands a live foreign VMM).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L100)

``` python
AttackBoxReclaimFn = Callable[[AttackBoxRecord, Path], None]
```

### DoctorProbe

An optional reachability probe for `inspect-ranges doctor`: `None` when healthy, else the failure detail (the `_host/backend.py` shape, aliased here so the realizer can import this module without the host-seam dependency chain).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L25)

``` python
DoctorProbe = Callable[[], str | None]
```

### ENV_VAR

The environment variable that selects an external attack-box provider, as `<module>.<factory>[:<config>]`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L22)

``` python
ENV_VAR = "INSPECT_RANGES_ATTACK_BOX"
```

## Provider Seam

### AttackBoxProvider

An external supplier of one range’s dedicated attack box.

`boot` receives the attachment and returns the running box’s handle; it owns the box’s lifecycle from that moment. `teardown` must be idempotent (a crash between the record write and `boot` reclaims a box that never existed) and must tolerate a token from a `boot` that half-completed.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L81)

``` python
class AttackBoxProvider(Protocol)
```

### AttackBoxCapabilities

What the backend declares it can do; a declared gap is recorded as evidence, never silently absent.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L92)

``` python
@dataclass(frozen=True)
class AttackBoxCapabilities
```

#### Attributes

`console_stream` bool  
Whether the provider delivers the attack box’s console stream. `False` records a declared gap on `console/<guest>`; `True` is not yet supported (no ingest path) and is refused.

### AttackBoxHandle

What a provider’s `boot` returns: the exec surface plus a reclaim token, nothing else.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L71)

``` python
@dataclass(frozen=True)
class AttackBoxHandle
```

#### Attributes

`exec_endpoint` [HybridEndpoint](../reference/attackbox.html.md#hybridendpoint)  
A unix socket serving the Cloud Hypervisor hybrid-vsock shape: the `CONNECT <port>` / `OK <port>` preamble, then the daemon wire protocol, one request per connection; the peer uid is enforced at every dial.

`reclaim_token` str  
Opaque provider state persisted in the attack-box record, handed back verbatim at `teardown`.

## Foothold

### FootholdAttachment

What the compiled plan hands an external attack-box provider: attachment in, nothing else.

Everything here is a plan fact; the provider supplies its own box (image, VMM, hardening) and attaches it behind the taps. `seed_dir` points at the rendered cloud-init seed for the attack box when the bundle carries one; a provider MAY consume it for in-guest network configuration and is never required to.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L54)

``` python
@dataclass(frozen=True)
class FootholdAttachment
```

#### Attributes

`cid` int  
The guest’s plan-reserved control-channel CID: a pure addressing token for exec routing, never a uid or tap-name promise.

### AttachedInterface

One L2 attachment point on a foothold segment, built inside the range container’s netns.

The tap is created and enslaved to the segment bridge inside the range netns before the provider sees it; the provider receives only the open fd. The host netns never carries a device for it, and the attachment dies with the fd (the tap is non-persistent) or with the range container’s netns, whichever comes first.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L31)

``` python
@dataclass(frozen=True)
class AttachedInterface
```

#### Attributes

`segment` str  
The attached network’s name in the plan.

`bridge` str  
The segment bridge device name inside the range netns (a fact; the tap is already enslaved).

`tap_fd` int  
The open tap fd. The provider owns it from handoff: pass it to the VMM and close it on teardown.

`mac` str  
The allocated guest MAC the external box MUST present on this segment (addressing and ACLs treat it as this guest).

`ip` IPv4Address  
The allocated interface address the external box MUST take.

`prefixlen` int  
The segment prefix length.

`gateway` IPv4Address \| None  
The segment gateway address, when the segment has one.

### HybridEndpoint

Where a Cloud Hypervisor guest’s hybrid-vsock socket is, and who must be listening on it.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_channel/vsock.py#L30)

``` python
class HybridEndpoint(NamedTuple)
```

#### Attributes

`peer_uid` int  
The uid the VMM runs as, as this host’s kernel reports it; any other socket owner is refused.

## Resolution and Records

### resolve_attack_box

THE resolver: an `INSPECT_RANGES_ATTACK_BOX` value (or a persisted record origin) to its backend bundle.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L169)

``` python
def resolve_attack_box(value: str, state_dir: Path) -> AttackBoxBackend
```

`value` str  

`state_dir` Path  

### parse_attack_box

Split an `INSPECT_RANGES_ATTACK_BOX` value against the grammar, without importing anything.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L156)

``` python
def parse_attack_box(value: str) -> ParsedAttackBox
```

`value` str  

### attack_box_origin

The configured attack-box origin, validated against the grammar; `None` when unset or empty.

Validation here is parse-only (no import), so a malformed value refuses loudly wherever the origin is first consulted, before any resource exists. A pinned program’s value is the one exception: its pin file is read here, so the origin carries the pin’s contents (`pinned.canonical_origin`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/backend.py#L207)

``` python
def attack_box_origin() -> str | None
```

### AttackBoxRecord

What `up` registers before the external provider boots: enough for any process to reclaim the foreign box.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/fc32484f22ebbc82b461a6987bc9afc29245796a/src/inspect_ranges/_attackbox/record.py#L29)

``` python
class AttackBoxRecord(BaseModel)
```

#### Attributes

`origin` str  
The full `INSPECT_RANGES_ATTACK_BOX` value, verbatim: re-resolved by import at teardown.

`reclaim_token` str  
The provider’s opaque teardown token (`AttackBoxHandle.reclaim_token`); empty until boot returns.

`exec_socket` str \| None  
The exec surface’s unix socket path, once booted (for out-of-band attach).

`exec_uid` int \| None  
The uid the exec socket’s peer must have (`SO_PEERCRED`), once booted.
