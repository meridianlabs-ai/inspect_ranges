from ipaddress import IPv4Address

import pytest
from inspect_ranges import revalidate_range
from inspect_ranges.types import (
    AclRule,
    Attacker,
    Host,
    Interface,
    Network,
    Os,
    RangeMeta,
    RangeSpec,
    Router,
)
from pydantic import ValidationError


def dmz_pivot() -> RangeSpec:
    """The overview's dmz-pivot example as typed construction (reads like the YAML)."""
    return RangeSpec(
        meta=RangeMeta(name="dmz-pivot", description="typed construction"),
        networks=[
            Network(name="dmz", cidr="10.80.10.0/24", mode="isolated"),
            Network(name="internal", cidr="10.80.20.0/24", mode="isolated"),
        ],
        routers=[
            Router(
                name="router",
                interfaces=[
                    Interface(network="dmz", ip="10.80.10.1"),
                    Interface(network="internal", ip="10.80.20.1"),
                ],
                acl=[AclRule(from_="dmz", to="internal", allow=["tcp/5432"])],
            )
        ],
        hosts=[
            Host(
                name="web",
                os=Os(type="linux"),
                image="acme/web-golden",
                interfaces=[Interface(network="dmz", ip="10.80.10.10")],
            ),
            Host(
                name="db",
                os=Os(type="linux"),
                image="acme/db-golden",
                interfaces=[Interface(network="internal")],
            ),
        ],
        attacker=Attacker(interfaces=[Interface(network="dmz")], entry="external"),
    )


def test_typed_construction_coerces_and_validates() -> None:
    spec = dmz_pivot()
    assert str(spec.networks[0].cidr) == "10.80.10.0/24"
    assert spec.routers[0].acl[0].from_ == "dmz"
    assert spec.attacker.egress == "none"


def test_revalidate_range_passes_through_a_consistent_spec() -> None:
    spec = dmz_pivot()
    checked = revalidate_range(spec)
    assert checked == spec
    assert checked is not spec


def test_guest_content_typed_construction() -> None:
    """Guest content constructs and validates through the typed surface."""
    from inspect_ranges.types import (
        ActiveDirectory,
        AdAcl,
        AdDomain,
        AdUser,
        Defense,
        Service,
        Telemetry,
        User,
        Vulnerability,
    )

    spec = dmz_pivot().model_copy(deep=True)
    spec.hosts[0].users = [User(name="alice", password="bacon")]
    spec.hosts[0].services = [Service(name="httpd", port=80)]
    spec.hosts[0].vulnerabilities = [
        Vulnerability(id="weak-thing", service="httpd", description="seeded")
    ]
    spec.defense = Defense(
        tier="D2", telemetry=[Telemetry(source="web", collector="agent", sink="db")]
    )
    spec.active_directory = ActiveDirectory(
        forest="corp.example",
        domains=[
            AdDomain(
                name="corp.example",
                netbios="CORP",
                dc="web",
                users=[AdUser(name="svc", spns=["HTTP/web.corp.example"])],
                acls=[AdAcl(principal="a", right="GenericAll", target="b")],
            )
        ],
    )
    checked = revalidate_range(spec)
    assert checked.active_directory is not None
    assert checked.active_directory.domains[0].acls[0].right == "GenericAll"


def test_unresolved_reference_to_declared_variable_is_rejected() -> None:
    """References resolve only on the YAML path; a typed spec carrying `{{name}}` for a declared variable is a construction mistake, while braces naming nothing declared stay legal scenario content."""
    from inspect_ranges.types import DataFile, User, Variable

    spec = dmz_pivot()
    spec.variables = {"admin_password": Variable(default="hunter2")}
    spec.hosts[0].users = [User(name="admin", password="{{admin_password}}")]
    with pytest.raises(ValidationError, match="unresolved reference"):
        revalidate_range(spec)

    spec.hosts[0].users = [User(name="admin", password="hunter2")]
    spec.hosts[0].data = [
        DataFile(path="/srv/app/payload.txt", description="{{secret_key}} and {{7*7}}")
    ]
    revalidate_range(spec)


def test_ipv6_values_are_gated() -> None:
    # the dual-stack types accept IPv6 structurally (the Network constructs),
    # but the spec-level gate rejects it until realization lands
    v6 = Network(name="lab", cidr="fd00::/8", mode="isolated")
    assert str(v6.cidr) == "fd00::/8"
    spec = dmz_pivot()
    spec.networks[0] = Network(name="dmz", cidr="fd00::/8", mode="isolated")
    with pytest.raises(ValidationError, match="not yet realized"):
        revalidate_range(spec)


def test_revalidate_range_catches_post_construction_mutation() -> None:
    spec = dmz_pivot()
    spec.hosts.append(
        Host(
            name="web",  # duplicate guest name
            os=Os(type="linux"),
            image="img",
            interfaces=[Interface(network="dmx")],  # undeclared network
        )
    )
    with pytest.raises(ValidationError) as excinfo:
        revalidate_range(spec)
    message = str(excinfo.value)
    assert "is not unique" in message
    assert "undeclared network 'dmx'" in message


def test_range_spec_hash_tracks_content() -> None:
    """Specs work as cache keys (Inspect hashes sandbox configs): equal content hashes equal, mutation changes the hash."""
    from inspect_ranges.types import Variable

    a = dmz_pivot()
    b = dmz_pivot()
    assert hash(a) == hash(b)
    assert {a: "cached"}[b] == "cached"
    # pydantic equality ignores dict insertion order; the hash must too
    a.variables = {"x": Variable(default=1), "y": Variable(default=2)}
    b.variables = {"y": Variable(default=2), "x": Variable(default=1)}
    assert a == b
    assert hash(a) == hash(b)
    # pydantic eq treats True == 1 (Python semantics); the hash must too
    a.variables = {"x": Variable(default=True)}
    b.variables = {"x": Variable(default=1)}
    assert a == b
    assert hash(a) == hash(b)
    b.hosts[0].hostname = "renamed"
    assert hash(a) != hash(b)


def _refuses(spec: RangeSpec, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        revalidate_range(spec)


def test_hardware_vocabulary_accepts_the_appliance_shape() -> None:
    """Well-formed hardware blocks, declared MACs, and opaque+readiness validate; an all-defaults block elides to nothing under default-insensitive dumping."""
    from inspect_ranges.types import Hardware, HardwareDisk, TcpReadiness

    spec = dmz_pivot()
    spec.hosts[0].hardware = Hardware(
        firmware="uefi",
        machine="pc",
        nic_model="e1000",
        video="vga",
        disks=[HardwareDisk(source="acme/data-golden", bus="ide")],
    )
    spec.hosts[0].interfaces[0].mac = "52:54:00:aa:bb:cc"
    spec.hosts[1].opaque = True
    spec.hosts[1].readiness = TcpReadiness(tcp=22, timeout=1500)
    spec.hosts[1].interfaces[0].ip = IPv4Address("10.80.20.9")
    revalidate_range(spec)
    with pytest.raises(ValidationError):
        TcpReadiness(tcp=22, timeout=10)  # below the 30s floor
    assert Hardware().model_dump(exclude_defaults=True) == {}


def test_hardware_vocabulary_gates_refuse() -> None:
    """Malformed/duplicate MACs, uefi-secure off q35, misscoped readiness, opaque content, opaque Windows, and an opaque foothold each refuse with their code in the message; the realized secure+tpm shape is accepted."""
    from inspect_ranges.types import Attacker, Hardware, HardwareDisk, TcpReadiness

    bad_mac = dmz_pivot()
    bad_mac.hosts[0].interfaces[0].mac = "not-a-mac"
    _refuses(bad_mac, "not six colon-separated hex octets")

    dupe = dmz_pivot()
    dupe.hosts[0].interfaces[0].mac = "52:54:00:aa:bb:cc"
    dupe.hosts[1].interfaces[0].mac = "52:54:00:AA:BB:CC"  # case-insensitive
    _refuses(dupe, "already declared")

    secure_pc = dmz_pivot()
    secure_pc.hosts[0].hardware = Hardware(firmware="uefi-secure", machine="pc")
    _refuses(secure_pc, "SMM lockbox exists on q35")

    secure = dmz_pivot()
    secure.hosts[0].hardware = Hardware(firmware="uefi-secure", tpm=True)
    revalidate_range(secure)  # the realized Windows 11 contract shape

    scoped = dmz_pivot()
    scoped.hosts[0].readiness = TcpReadiness(tcp=22)
    _refuses(scoped, "not\\s+opaque")

    from inspect_ranges.types import ProvisioningStep

    plain_opaque = dmz_pivot()
    plain_opaque.hosts[1].opaque = True
    plain_opaque.hosts[1].interfaces[0].ip = IPv4Address("10.80.20.9")
    revalidate_range(plain_opaque)  # opaque with no content is the valid shape

    unaddressed = dmz_pivot()
    unaddressed.hosts[1].opaque = True
    _refuses(unaddressed, "cannot invent one")

    ide_on_q35 = dmz_pivot()
    ide_on_q35.hosts[0].hardware = Hardware(disks=[HardwareDisk(size_gb=5, bus="ide")])
    _refuses(ide_on_q35, "no\\s+IDE controller")
    ide_on_pc = dmz_pivot()
    ide_on_pc.hosts[0].hardware = Hardware(
        machine="pc", disks=[HardwareDisk(size_gb=5, bus="ide")]
    )
    revalidate_range(ide_on_pc)

    too_many = dmz_pivot()
    too_many.hosts[0].hardware = Hardware(
        disks=[HardwareDisk(size_gb=1) for _ in range(15)]
    )
    _refuses(too_many, "more extra disks")

    content = dmz_pivot()
    content.hosts[0].opaque = True
    content.hosts[0].provisioning = [ProvisioningStep(recipe="acme.web")]
    _refuses(content, "nothing could realize")

    windows = dmz_pivot()
    windows.hosts[1].os = Os(type="windows", version="server-2022")
    windows.hosts[1].opaque = True
    _refuses(windows, "opaque Windows")

    foothold = dmz_pivot()
    foothold.hosts[0].opaque = True
    foothold.attacker = Attacker(host="web", entry="assumed-breach")
    _refuses(foothold, "foothold")


def test_hardware_disk_takes_exactly_one_source() -> None:
    from inspect_ranges.types import HardwareDisk

    HardwareDisk(size_gb=100)
    HardwareDisk(source="acme/data")
    with pytest.raises(ValidationError, match="exactly one"):
        HardwareDisk(size_gb=100, source="acme/data")
    with pytest.raises(ValidationError, match="exactly one"):
        HardwareDisk()
