"""`range.yaml` schema v0.1: the strict, runtime-consumed core of a range definition.

v0.1 deliberately covers only the five sections the runtime consumes — `range`, `networks`, `routers`, `hosts`, `attacker` — and rejects everything else loudly. Sections awaiting real design (`attack_path`, `goals`, `variables`, `defense`, `vulnerabilities`, guest configuration, ...) are excluded entirely; see `design/inspect-ranges/schema-v0.1-scope.md` for the deferral rationale and each example range's `deferred.yaml` for parked content.

Load a spec with `load_range`, or validate pre-parsed data with `RangeSpec.model_validate`. The published JSON Schema is `range_json_schema` (also `inspect-ranges schema` on the CLI).
"""

import re
from datetime import date
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_ALLOW_RULE = re.compile(r"^(tcp|udp)/(\d{1,5})(?:-(\d{1,5}))?$")


class _StrictModel(BaseModel):
    """Base for all schema models: unknown keys are errors, aliases are accepted."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SourceMeta(_StrictModel):
    """Provenance of a range definition: the upstream artifact it derives from."""

    artifact: str
    """The upstream artifact, e.g. `vulhub (github.com/vulhub/vulhub), zabbix/CVE-2016-10134/`."""

    license: str
    """Upstream license identifier, e.g. `MIT`."""

    files: list[str]
    """Vendored upstream files this definition was translated from."""

    upstream_substrate: str
    """What the upstream artifact runs on, e.g. `Docker Compose`."""

    fetched: date
    """When the upstream files were fetched."""

    commit: str
    """Upstream commit the vendored files match."""


class RangeMeta(_StrictModel):
    """Identity and provenance of the range."""

    name: str
    """Short identifier, e.g. `vulhub-zabbix`."""

    title: str
    """One-line human-readable title."""

    schema_version: Literal["0.1"]
    """Schema version this definition targets."""

    description: str
    """What the range is and why it exists."""

    source: SourceMeta
    """Upstream provenance."""


class DnsRecord(_StrictModel):
    """A name record served on a network."""

    name: str
    """Hostname to resolve."""

    ip: IPv4Address | None = None
    """Address, when not derivable from the named guest's interface."""


class DnsConfig(_StrictModel):
    """Per-network DNS, as a union of the shapes real ranges need.

    `records` serves name-based discovery on flat networks; `nameservers` points guests at external resolvers; `authoritative` names guests (e.g. domain controllers) that are the network's DNS servers, optionally chaining to `forwarder`.
    """

    records: list[DnsRecord] | None = None
    """Name records served by the range for this network."""

    nameservers: list[IPv4Address] | None = None
    """External resolvers handed to guests."""

    authoritative: list[str] | None = None
    """Guests that act as this network's DNS servers, in resolution order."""

    forwarder: IPv4Address | None = None
    """Upstream forwarder for the authoritative chain."""


class Network(_StrictModel):
    """A layer-2 segment with its addressing and egress posture."""

    name: str
    """Segment name, unique within the range."""

    cidr: IPv4Network
    """Subnet, e.g. `10.10.10.0/24`."""

    mode: Literal["isolated", "nat", "routed"]
    """Egress posture: `isolated` (no egress), `nat`, or `routed`."""

    dhcp: bool = False
    """Whether guests on this network get addresses via DHCP (default: static)."""

    dns: DnsConfig | None = None
    """DNS behavior on this network."""


class Interface(_StrictModel):
    """A guest's attachment to a network."""

    network: str
    """Name of a declared network."""

    ip: IPv4Address | None = None
    """Static address within the network's subnet; omitted means IPAM-allocated."""


class Os(_StrictModel):
    """Guest operating system."""

    type: Literal["linux", "windows"]
    """OS family."""

    distro: str | None = None
    """Linux distribution, e.g. `ubuntu-20.04`."""

    version: str | None = None
    """Windows version, e.g. `server-2019`."""


class Resources(_StrictModel):
    """Backend-neutral guest sizing."""

    cpus: int = Field(ge=1)
    """Virtual CPU count."""

    memory_mb: int = Field(ge=64)
    """Memory in MiB."""

    disk_gb: int | None = Field(default=None, ge=1)
    """Disk size in GiB, when the image default is not enough."""


class AclRule(_StrictModel):
    """One allow rule on a router: new connections `from` one network `to` another.

    Semantics are default-deny and stateful: anything not allowed is dropped, return traffic of allowed flows always passes.
    """

    from_: str = Field(alias="from")
    """Source network name."""

    to: str
    """Destination network name."""

    allow: list[str]
    """Allowed services as `proto/port` or `proto/lo-hi` entries, e.g. `tcp/5432`, `tcp/1-65535`; empty allows nothing."""

    @model_validator(mode="after")
    def _check_allow_entries(self) -> "AclRule":
        for entry in self.allow:
            match = _ALLOW_RULE.match(entry)
            if match is None:
                raise ValueError(
                    f"ACL allow entry {entry!r} must be proto/port or proto/lo-hi, e.g. tcp/5432"
                )
            low = int(match.group(2))
            high = int(match.group(3)) if match.group(3) else low
            if not 0 < low <= high < 65536:
                raise ValueError(f"ACL allow entry {entry!r} has an invalid port range")
        return self


class Router(_StrictModel):
    """A gateway guest joining two or more networks, carrying the inter-segment ACL."""

    name: str
    """Guest name, unique within the range."""

    os: Os | None = None
    """Operating system, when the router is a full declared guest."""

    image: str | None = None
    """Image reference; omitted means the backend's default router appliance."""

    resources: Resources | None = None
    """Sizing; omitted means backend defaults."""

    interfaces: list[Interface] = Field(min_length=2)
    """One attachment per joined network (at least two)."""

    acl: list[AclRule] = []
    """Inter-segment policy enforced on this router (default-deny, stateful)."""


class Host(_StrictModel):
    """A target guest."""

    name: str
    """Guest name, unique within the range."""

    hostname: str | None = None
    """In-guest hostname, when it differs from `name`."""

    fqdn: str | None = None
    """Fully qualified name, when the range's DNS should serve it."""

    os: Os
    """Operating system."""

    image: str
    """Image reference the guest boots from."""

    resources: Resources | None = None
    """Sizing; omitted means backend defaults."""

    interfaces: list[Interface] = Field(min_length=1)
    """Network attachments (explicit; v0.1 has no implicit attachment)."""


class Attacker(_StrictModel):
    """The agent's foothold: either a dedicated attack box or an existing host.

    Declare `host` to start on a declared host (assumed breach), or `interfaces` (plus optionally `name`, `image`, `resources`) to boot a dedicated attack box.
    """

    name: str = "attacker"
    """Attack box guest name (ignored when `host` is set)."""

    host: str | None = None
    """Name of a declared host to use as the foothold instead of a dedicated box."""

    image: str | None = None
    """Attack box image; omitted means the backend's standard attack image."""

    resources: Resources | None = None
    """Attack box sizing."""

    interfaces: list[Interface] | None = None
    """Attack box network attachments (required unless `host` is set)."""

    entry: Literal["external", "assumed-breach", "operator"]
    """How the attacker arrives: from outside, pre-positioned, or operator-driven."""

    egress: Literal["none", "open"] = "none"
    """Attacker-reachable egress from the range (default: none)."""

    @model_validator(mode="after")
    def _check_foothold(self) -> "Attacker":
        if self.host is not None:
            extras = [
                field
                for field in ("image", "resources", "interfaces")
                if getattr(self, field) is not None
            ]
            if extras:
                raise ValueError(
                    f"attacker with host= must not also declare {', '.join(extras)}"
                )
        elif self.interfaces is None or not self.interfaces:
            raise ValueError("attacker needs either host= or at least one interface")
        return self


class RangeSpec(_StrictModel):
    """A complete v0.1 range definition."""

    meta: RangeMeta = Field(alias="range")
    """Identity and provenance (the `range:` section)."""

    networks: list[Network] = Field(min_length=1)
    """Layer-2 segments."""

    routers: list[Router] = []
    """Gateway guests joining segments."""

    hosts: list[Host] = Field(min_length=1)
    """Target guests."""

    attacker: Attacker
    """The agent's foothold."""

    @model_validator(mode="after")
    def _check_references(self) -> "RangeSpec":
        networks = {network.name: network for network in self.networks}
        if len(networks) != len(self.networks):
            raise ValueError("network names must be unique")

        guests = (
            [(host.name, host.interfaces) for host in self.hosts]
            + [(router.name, router.interfaces) for router in self.routers]
            + (
                [(self.attacker.name, self.attacker.interfaces or [])]
                if self.attacker.host is None
                else []
            )
        )
        names = [name for name, _ in guests]
        if len(set(names)) != len(names):
            raise ValueError("guest names (hosts, routers, attacker) must be unique")

        for name, interfaces in guests:
            for interface in interfaces:
                network = networks.get(interface.network)
                if network is None:
                    raise ValueError(
                        f"guest {name!r} attaches to undeclared network {interface.network!r}"
                    )
                if interface.ip is not None and interface.ip not in network.cidr:
                    raise ValueError(
                        f"guest {name!r} address {interface.ip} is outside {network.name!r} ({network.cidr})"
                    )

        for router in self.routers:
            for rule in router.acl:
                for endpoint in (rule.from_, rule.to):
                    if endpoint not in networks:
                        raise ValueError(
                            f"router {router.name!r} ACL references undeclared network {endpoint!r}"
                        )

        if self.attacker.host is not None and self.attacker.host not in {
            host.name for host in self.hosts
        }:
            raise ValueError(
                f"attacker foothold references undeclared host {self.attacker.host!r}"
            )
        return self


def load_range(path: Path) -> RangeSpec:
    """Load and validate a `range.yaml` file.

    Args:
        path: Path to the YAML file.

    Returns:
        The validated spec.

    Raises:
        ValueError: The file is not a YAML mapping.
        yaml.YAMLError: The file is not parseable YAML.
        pydantic.ValidationError: The content does not satisfy schema v0.1.
    """
    data: Any = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return RangeSpec.model_validate(data)


def range_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for `range.yaml` v0.1 (aliased field names, e.g. `from`)."""
    return RangeSpec.model_json_schema(by_alias=True)
