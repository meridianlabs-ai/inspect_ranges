# inspect_ranges.types – Inspect Ranges

The typed form of a range definition. A [RangeSpec](../reference/types.html.md#rangespec) is accepted directly as sandbox configuration (`sandbox=("libvirt_range", RangeSpec(...))`), interchangeably with a `range.yaml` path. Construction reads like the YAML: strings coerce to address types (including under strict type checking), literals take plain strings, and nested dicts are accepted via `model_validate`. The one spelling divergence is [AclRule](../reference/types.html.md#aclrule)’s `from_=` keyword for the YAML `from:`.

Models validate fully at construction (structural and cross-reference checks) and stay mutable for programmatic building; every consumer boundary revalidates (see `revalidate_range`). See [Defining Ranges](../ranges.html.md) for a guided tour of the syntax.

## Range

### RangeSpec

A complete v0.1 range definition.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L885)

``` python
class RangeSpec(_StrictModel)
```

#### Attributes

`meta` [RangeMeta](../reference/types.html.md#rangemeta)  
Identity and provenance (the `range:` section in YAML; `meta=` in typed construction).

`networks` list\[[Network](../reference/types.html.md#network)\]  
Layer-2 segments.

`routers` list\[[Router](../reference/types.html.md#router)\]  
Gateway guests joining segments.

`hosts` list\[[Host](../reference/types.html.md#host)\]  
Target guests.

`attacker` [Attacker](../reference/types.html.md#attacker)  
The agent’s foothold.

`defense` [Defense](../reference/types.html.md#defense) \| None  
The range’s defensive posture (omitted means D0, no defenders).

`active_directory` [ActiveDirectory](../reference/types.html.md#activedirectory) \| None  
Active Directory identity data, for domain ranges.

`variables` dict\[str, [Variable](../reference/types.html.md#variable)\]  
Per-instance randomized values, referenced as `{name}` in YAML scalars (defaults substitute at load).

### RangeMeta

Identity of the range.

Upstream provenance is a convention, not schema: record it in a `source.md` next to the `range.yaml`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L82)

``` python
class RangeMeta(_StrictModel)
```

#### Attributes

`name` str  
Short identifier, e.g. `vulhub-zabbix`.

`schema_version` Literal\['0.1', '0.2', '0.3'\]  
Schema version this definition targets (omitted means `0.1`; `0.2` is the networking vocabulary, `0.3` adds guest configuration).

`description` str  
What the range is and why it exists.

## Guests

### Host

A target guest.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L666)

``` python
class Host(_StrictModel)
```

#### Attributes

`name` str  
Guest name, unique within the range.

`hostname` str \| None  
In-guest hostname, when it differs from `name`.

`fqdn` str \| None  
Fully qualified name, when the range’s DNS should serve it.

`os` [Os](../reference/types.html.md#os)  
Operating system.

`image` str  
Image reference the guest boots from.

`resources` [Resources](../reference/types.html.md#resources) \| None  
Sizing; omitted means backend defaults.

`interfaces` list\[[Interface](../reference/types.html.md#interface)\]  
Network attachments (explicit; v0.1 has no implicit attachment).

`users` list\[[User](../reference/types.html.md#user)\]  
Local accounts (converged state; applied and verified at build).

`services` list\[[Service](../reference/types.html.md#service)\]  
The converged listening surface (assertions, verified at build).

`vulnerabilities` list\[[Vulnerability](../reference/types.html.md#vulnerability)\]  
Seeded exploitable weaknesses.

`misconfigurations` list\[[Misconfiguration](../reference/types.html.md#misconfiguration)\]  
Seeded misconfigurations.

`data` list\[[DataFile](../reference/types.html.md#datafile)\]  
Planted scenario files.

`defense` [HostDefense](../reference/types.html.md#hostdefense) \| None  
Per-host protection toggles.

`provisioning` list\[[ProvisioningStep](../reference/types.html.md#provisioningstep)\]  
Build-time recipe references, in order.

`roles` list\[str\]  
Functional role tags the build realizes (e.g. `domain-controller`, `dns`, `adcs`).

`scheduled_activity` list\[[ScheduledActivity](../reference/types.html.md#scheduledactivity)\]  
Recurring in-guest behavior simulation.

### Router

A gateway guest joining two or more networks, carrying the inter-segment ACL.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L638)

``` python
class Router(_StrictModel)
```

#### Attributes

`name` str  
Guest name, unique within the range.

`os` [Os](../reference/types.html.md#os) \| None  
Operating system, when the router is a full declared guest.

`image` str \| None  
Image reference; omitted means the backend’s default router appliance.

`resources` [Resources](../reference/types.html.md#resources) \| None  
Sizing; omitted means backend defaults.

`interfaces` list\[[Interface](../reference/types.html.md#interface)\]  
One attachment per joined network (at least two).

`routes` list\[[Route](../reference/types.html.md#route)\]  
Static routes to segments reached through other routers.

`users` list\[[User](../reference/types.html.md#user)\]  
Local accounts (converged state; applied and verified at build).

`acl` list\[[AclRule](../reference/types.html.md#aclrule)\]  
Inter-segment policy enforced on this router (default-deny, stateful; endpoints may be routed, not only attached).

### Attacker

The agent’s foothold: either a dedicated attack box or an existing host.

Declare `host` to start on a declared host (assumed breach), or `interfaces` (plus optionally `name`, `image`, `resources`) to boot a dedicated attack box.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L718)

``` python
class Attacker(_StrictModel)
```

#### Attributes

`name` str  
Attack box guest name (ignored when `host` is set).

`host` str \| None  
Name of a declared host to use as the foothold instead of a dedicated box.

`image` str \| None  
Attack box image; omitted means the backend’s standard attack image.

`resources` [Resources](../reference/types.html.md#resources) \| None  
Attack box sizing.

`interfaces` list\[[Interface](../reference/types.html.md#interface)\] \| None  
Attack box network attachments (required unless `host` is set).

`entry` Literal\['external', 'assumed-breach', 'operator'\]  
How the attacker arrives: from outside, pre-positioned, or operator-driven.

`egress` Literal\['none', 'open'\] \| [EgressPolicy](../reference/types.html.md#egresspolicy)  
Attacker-reachable egress from the range: `none` (default), `open`, or a scoped allowlist. Attacker egress composes ahead of network egress: `none` drops the attacker’s flows even on a network with an allowlist.

### Os

Guest operating system.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L323)

``` python
class Os(_StrictModel)
```

#### Attributes

`type` Literal\['linux', 'windows'\]  
OS family.

`distro` str \| None  
Linux distribution, e.g. `ubuntu-20.04`.

`version` str \| None  
Windows version, e.g. `server-2019`.

### Resources

Backend-neutral guest sizing.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L336)

``` python
class Resources(_StrictModel)
```

#### Attributes

`cpus` int  
Virtual CPU count.

`memory_mb` int  
Memory in MiB.

`disk_gb` int \| None  
Disk size in GiB, when the image default is not enough.

## Guest Content

### User

A local account on a guest.

Scenario credentials are scenario content and belong in the definition in plaintext; per-sample proof material (flags, canaries) never appears here. Domain accounts live in `active_directory`, not on hosts.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L349)

``` python
class User(_StrictModel)
```

#### Attributes

`name` str  
Account name.

`password` str \| None  
Password, when the scenario fixes one.

`groups` list\[str\]  
Local group memberships.

`note` str \| None  
Free-text intent, e.g. why the account exists or what makes it interesting.

### Credentials

A credential pair a service accepts.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L368)

``` python
class Credentials(_StrictModel)
```

#### Attributes

`user` str  
Account name.

`password` str  
Password.

### Service

An assertion about a guest’s converged listening surface.

Services are declarations, never an install language: the build satisfies them (via a provisioning recipe, content baked into the image, or a checkpoint) and verifies them before the range ships. Installation itself belongs in `provisioning`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L378)

``` python
class Service(_StrictModel)
```

#### Attributes

`name` str  
Service name, unique on the host (vulnerabilities reference it).

`port` int \| None  
Listening port, when fixed.

`version` str \| None  
Expected version, when the scenario depends on it.

`credentials` [Credentials](../reference/types.html.md#credentials) \| None  
Credentials the service accepts, when scenario-relevant.

`note` str \| None  
Free-text detail.

### Vulnerability

A seeded exploitable weakness on a guest.

Exploitable vulnerabilities and misconfigurations are distinct lists because real intrusions lean heavily on the second; the list itself is the classification.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L400)

``` python
class Vulnerability(_StrictModel)
```

#### Attributes

`id` str  
Stable identifier, ours (e.g. `weak-telnet-password`, `adcs-esc1`).

`cve` str \| None  
CVE identifier, when one applies.

`service` str \| None  
The host service this weakness lives in, by `services[].name`.

`description` str  
What the weakness is and how it is reachable.

### Misconfiguration

A seeded misconfiguration on a guest (weak policy, dangerous sudoers line, disabled protection).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L419)

``` python
class Misconfiguration(_StrictModel)
```

#### Attributes

`id` str  
Stable identifier, ours.

`description` str  
What is misconfigured and why it matters.

### DataFile

A file planted on a guest as scenario content.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L429)

``` python
class DataFile(_StrictModel)
```

#### Attributes

`path` str  
Absolute in-guest path.

`description` str \| None  
What the file represents.

`sensitive` bool  
Whether the file is a scenario target (e.g. data worth exfiltrating).

`contents` str \| None  
Small inline contents; larger content is build material referenced by provisioning.

### ProvisioningStep

A build-time recipe reference, applied in list order.

Recipes run at build time and never per sample; their output is captured into images and checkpoints. The recipe language itself is deliberately out of the definition: a step names a recipe and its inputs, nothing more.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L458)

``` python
class ProvisioningStep(_StrictModel)
```

#### Attributes

`recipe` str  
Recipe reference, e.g. `P4T12ICK.ludus_ar_windows` or `scripts/promote-forest`.

`version` str \| None  
Recipe version, recorded in the build manifest.

`vars` dict\[str, str \| int \| bool\]  
Inputs passed to the recipe.

### ScheduledActivity

Recurring in-guest behavior, simulating users or defenders (bot scripts, scheduled tasks).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L474)

``` python
class ScheduledActivity(_StrictModel)
```

#### Attributes

`script` str  
Behavior reference, e.g. `asrep_roasting.ps1` or a recipe-style name.

`schedule` str \| None  
When it runs, when the scenario fixes it (e.g. a cron expression or an interval).

`user` str \| None  
The account the activity runs as, when scenario-relevant (e.g. for token-theft surface).

`note` str \| None  
Free-text intent.

### Variable

A named per-instance value: drawn fresh for each generated instance, with a required default.

Definitions reference variables as `{name}` in YAML scalars; loading substitutes the defaults before validation, so a whole-scalar reference takes the variable’s typed value (`port: "{{telnet_port}}"` validates as an integer) and embedded references interpolate as text. Required defaults mean every definition always validates and realizes concretely; the per-instance draw arrives with the generation layer (gated at planning by `randomization-not-realized`). Python authors draw values and construct concretely instead of using references.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L490)

``` python
class Variable(_StrictModel)
```

#### Attributes

`default` str \| int \| bool  
The value used until generation draws one, and the fallback definition of the variable’s type.

`type` Literal\['text', 'password', 'port', 'int', 'choice'\] \| None  
What to draw, when generation lands; omitted means the default’s own type.

`min` int \| None  
Lower bound for numeric draws.

`max` int \| None  
Upper bound for numeric draws.

`choices` list\[str\] \| None  
The candidate set, for `type: choice`.

`description` str \| None  
What the variable controls.

## Defense

### Defense

The range’s defensive posture, on the D0 (no defenders) to D5 (adaptive defender) spectrum.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L790)

``` python
class Defense(_StrictModel)
```

#### Attributes

`tier` Literal\['D0', 'D1', 'D2', 'D3', 'D4', 'D5'\]  
How much the environment fights back: D0 none, D1 static hardening, D2 passive detection, D3 scripted response, D4 autonomous EDR, D5 adaptive.

`description` str \| None  
What the posture consists of.

`telemetry` list\[[Telemetry](../reference/types.html.md#telemetry)\]  
Telemetry flows, when the range records or forwards signals.

### HostDefense

Per-host protection toggles (typed knowns; extended when evidence forces).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L445)

``` python
class HostDefense(_StrictModel)
```

#### Attributes

`defender` bool \| None  
Microsoft Defender on or off.

`firewall` bool \| None  
Host firewall on or off.

`windows_update` bool \| None  
Windows Update on or off.

### Telemetry

One telemetry flow: which guest’s signals reach which sink.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L777)

``` python
class Telemetry(_StrictModel)
```

#### Attributes

`source` str  
The observed guest, by name.

`collector` str  
What gathers the signals, e.g. `Sysmon/WinEventLog` or an agent name.

`sink` str  
Where the signals land: a declared guest name, or a description of an external sink.

## Active Directory

### ActiveDirectory

Range-scoped Active Directory identity data.

Identity is declared here, not on hosts, because accounts exist in the domain. The build realizes it (promotion, joins, account and ACL seeding) and captures the converged result; see `design/inspect-ranges/range-build.md`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L872)

``` python
class ActiveDirectory(_StrictModel)
```

#### Attributes

`forest` str  
Forest root domain name.

`domains` list\[[AdDomain](../reference/types.html.md#addomain)\]  
The forest’s domains.

### AdDomain

One domain in the forest.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L850)

``` python
class AdDomain(_StrictModel)
```

#### Attributes

`name` str  
DNS name of the domain.

`netbios` str  
NetBIOS name.

`dc` str  
The domain controller, by declared guest name.

`parent` str \| None  
Parent domain name, for child domains.

`users` list\[[AdUser](../reference/types.html.md#aduser)\]  
Domain accounts of note.

`acls` list\[[AdAcl](../reference/types.html.md#adacl)\]  
Seeded ACL-abuse edges.

### AdUser

A domain account.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L831)

``` python
class AdUser(_StrictModel)
```

#### Attributes

`name` str  
sAMAccountName.

`password` str \| None  
Password, when the scenario fixes one.

`groups` list\[str\]  
Group memberships.

`spns` list\[str\]  
Service principal names (kerberoastable surface).

`note` str \| None  
Free-text intent, e.g. what makes the account interesting.

### AdAcl

One seeded ACL-abuse edge: `principal` holds `right` over `target`.

Principals and targets are names as AD knows them (users, groups, OUs, or computer objects) and are not cross-validated against declared users this round.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L815)

``` python
class AdAcl(_StrictModel)
```

#### Attributes

`principal` str  
Who holds the right.

`right` [AdRight](../reference/types.html.md#adright)  
The right held.

`target` str  
What the right applies to.

### AdRight

Seeded AD ACL rights (the vocabulary observed in surveyed ranges; extended when evidence forces).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L803)

``` python
AdRight = Literal[
    "GenericAll",
    "GenericWrite",
    "WriteDacl",
    "WriteOwner",
    "ForceChangePassword",
    "SelfMembership",
    "AddMember",
]
```

## Networks

### Network

A layer-2 segment with its addressing and egress posture.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L253)

``` python
class Network(_StrictModel)
```

#### Attributes

`name` str  
Segment name, unique within the range.

`cidr` [AnyIPNetwork](../reference/types.html.md#anyipnetwork)  
Subnet, e.g. `10.10.10.0/24` (IPv6 subnets are gated by `ipv6-not-realized` until realization lands).

`mode` Literal\['isolated', 'nat', 'routed'\]  
Egress posture: `isolated` (no egress), `nat`, or `routed`.

`dhcp` bool  
Whether guests on this network get addresses via DHCP (default: static).

`dns` [DnsConfig](../reference/types.html.md#dnsconfig) \| None  
DNS behavior on this network.

`gateway` str \| None  
The router that is this network’s default gateway; required only when more than one router attaches (a single attached router is elected implicitly).

`egress` [EgressPolicy](../reference/types.html.md#egresspolicy) \| None  
Scoped egress allowlist; only meaningful with `mode: nat` (the hypervisor NATs exactly these flows out).

### Interface

A guest’s attachment to a network.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L307)

``` python
class Interface(_StrictModel)
```

#### Attributes

`network` str  
Name of a declared network.

`ip` [AnyIPAddress](../reference/types.html.md#anyipaddress) \| None  
Static address within the network’s subnet; omitted means IPAM-allocated.

### DnsConfig

Per-network DNS, as a union of the shapes real ranges need.

`records` serves name-based discovery on flat networks; `nameservers` points guests at external resolvers; `authoritative` names guests (e.g. domain controllers) that are the network’s DNS servers, optionally chaining to `forwarder`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L114)

``` python
class DnsConfig(_StrictModel)
```

#### Attributes

`records` list\[[DnsRecord](../reference/types.html.md#dnsrecord)\] \| None  
Name records served by the range for this network.

`nameservers` list\[[AnyIPAddress](../reference/types.html.md#anyipaddress)\] \| None  
External resolvers handed to guests.

`authoritative` list\[str\] \| None  
Guests that act as this network’s DNS servers, in resolution order.

`forwarder` [AnyIPAddress](../reference/types.html.md#anyipaddress) \| None  
Upstream forwarder for the authoritative chain.

### DnsRecord

A name record served on a network.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L98)

``` python
class DnsRecord(_StrictModel)
```

#### Attributes

`name` str  
Hostname to resolve.

`ip` [AnyIPAddress](../reference/types.html.md#anyipaddress) \| None  
Address, when not derivable from the named guest’s interface.

### EgressPolicy

A scoped egress allowlist: exactly what may leave, nothing else.

Entries are `CIDR[:proto/port]` (a bare address is its `/32`; omitting the service allows all traffic to the CIDR) or `FQDN:proto/port`. FQDN entries are in the vocabulary but gated by `egress-fqdn-not-realized` until their realization lands (networking-v0.2 §3).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L202)

``` python
class EgressPolicy(_StrictModel)
```

#### Attributes

`allow` list\[str\]  
Allowlist entries, e.g. `198.51.100.7:tcp/443`, `0.0.0.0/0:udp/123`; empty allows nothing.

### Route

A static route on a router, for traffic to segments it reaches through another router.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L622)

``` python
class Route(_StrictModel)
```

#### Attributes

`to` [AnyIPNetwork](../reference/types.html.md#anyipnetwork)  
Destination subnet.

`via` [AnyIPAddress](../reference/types.html.md#anyipaddress)  
Next hop; must be an address inside one of the router’s attached networks.

### AclRule

One ordered rule on a router, carrying exactly one of `allow:` or `deny:`.

Rules evaluate first-match in list order against new connections `from` one endpoint `to` another; anything no rule matches is dropped (default-deny), and return traffic of allowed flows always passes (stateful). Endpoints are a network name, a guest name (resolved to its allocated addresses at plan time), or a CIDR (`/32` for a literal host, `0.0.0.0/0` for any). `deny` exists for carve-outs inside a broader allow. In typed construction the source field is spelled `from_` (the YAML surface keeps `from:`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L555)

``` python
class AclRule(_StrictModel)
```

#### Attributes

`from_` str  
Source endpoint: network name, guest name, or CIDR (`from:` in YAML; `from_=` in typed construction).

`to` str  
Destination endpoint: network name, guest name, or CIDR.

`allow` list\[str\] \| None  
Services to allow, as `proto/port`, `proto/lo-hi`, or `icmp` entries, e.g. `tcp/5432`, `tcp/1-65535`; empty allows nothing.

`deny` list\[str\] \| None  
Services to drop at this point in the rule order (same entry syntax as `allow`).

### AnyIPAddress

Either address family. IPv6 values validate structurally but are rejected by the `ipv6-not-realized` gate until their realization lands (networking-v0.2 §4).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L26)

``` python
AnyIPAddress = IPv4Address | IPv6Address
```

### AnyIPNetwork

Either address family. IPv6 values validate structurally but are rejected by the `ipv6-not-realized` gate until their realization lands (networking-v0.2 §4).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/types.py#L29)

``` python
AnyIPNetwork = IPv4Network | IPv6Network
```

## Diagnostics

### Issue

One problem found in a range definition.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/_diagnostics.py#L46)

``` python
class Issue(BaseModel)
```

#### Attributes

`code` str  
Stable kebab-case identifier, e.g. `undeclared-network`.

`severity` Severity  
Whether the issue blocks use of the spec.

`path` tuple\[PathElement, ...\]  
Location within the spec, e.g. `("networks", 0, "cidr")`.

`line` int \| None  
1-based source line, when the YAML parse can supply it.

`col` int \| None  
1-based source column, when the YAML parse can supply it.

`message` str  
What is wrong.

`hint` str \| None  
Actionable suggestion, e.g. a did-you-mean or where deferred content goes.

`path_str` str  
The path rendered as `networks[0].cidr`, or `(root)` for the document root.

### ValidationReport

Every issue found in one `range.yaml`, with rendering helpers.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/_diagnostics.py#L87)

``` python
class ValidationReport(BaseModel)
```

#### Attributes

`file` str  
The validated file path, as given.

`issues` list\[[Issue](../reference/types.html.md#issue)\]  
All issues found, in source order where positions are known.

`semantic_checked` bool  
False when structural errors prevented the cross-reference checks from running.

`spec` Any \| None  
The validated [RangeSpec](../reference/types.html.md#rangespec) when the file is valid, for callers that need it.

`valid` bool  
True when no error-severity issues were found.

#### Methods

render  
Render the report as aligned, human-readable text (warnings do not invalidate).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/_diagnostics.py#L109)

``` python
def render(self) -> str
```

to_json  
Return the report as JSON-serializable data with stable field names.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/96c88cf2ba742011f10c089afd102fc091acbe67/src/inspect_ranges/_diagnostics.py#L143)

``` python
def to_json(self) -> dict[str, Any]
```
