from pathlib import Path
from typing import Any

import pytest
import yaml
from inspect_ranges.schema import RangeSpec, load_range, range_json_schema
from pydantic import ValidationError

EXAMPLES = sorted(
    (Path(__file__).parent.parent / "design/inspect-ranges/ranges").glob("*/range.yaml")
)

MINIMAL = """
range:
  name: minimal
  description: minimal valid range
networks:
  - { name: lab, cidr: 10.0.0.0/24, mode: isolated }
hosts:
  - name: web
    os: { type: linux }
    image: img
    interfaces: [{ network: lab, ip: 10.0.0.10 }]
attacker:
  interfaces: [{ network: lab }]
  entry: external
"""


def _with(overrides_yaml: str) -> Any:
    data = yaml.safe_load(MINIMAL)
    data.update(yaml.safe_load(overrides_yaml))
    return data


def test_examples_validate() -> None:
    assert len(EXAMPLES) == 6
    for path in EXAMPLES:
        spec = load_range(path)
        assert spec.meta.schema_version == "0.1"


def test_minimal_spec_validates() -> None:
    spec = RangeSpec.model_validate(yaml.safe_load(MINIMAL))
    assert spec.attacker.name == "attacker"
    assert spec.attacker.egress == "none"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param("attack_path: []", "attack_path", id="deferred-top-level-key"),
        pytest.param(
            """
            hosts:
              - name: web
                os: { type: linux }
                image: img
                interfaces: [{ network: lab }]
                services: []
            """,
            "services",
            id="deferred-host-key",
        ),
        pytest.param(
            "networks: [{ name: lab, cidr: banana, mode: isolated }]",
            "cidr",
            id="bad-cidr",
        ),
        pytest.param(
            """
            hosts:
              - name: web
                os: { type: linux }
                image: img
                interfaces: [{ network: lab, ip: 10.9.9.9 }]
            """,
            "outside",
            id="ip-outside-subnet",
        ),
        pytest.param(
            """
            hosts:
              - name: web
                os: { type: linux }
                image: img
                interfaces: [{ network: wan }]
            """,
            "undeclared network",
            id="dangling-network-ref",
        ),
        pytest.param(
            """
            hosts:
              - name: attacker
                os: { type: linux }
                image: img
                interfaces: [{ network: lab }]
            """,
            "unique",
            id="guest-name-collision-with-attacker",
        ),
        pytest.param(
            """
            routers:
              - name: r
                interfaces: [{ network: lab }, { network: lab }]
                acl: [{ from: lab, to: lab, allow: ["25"] }]
            """,
            "proto/port",
            id="bad-allow-entry",
        ),
        pytest.param(
            """
            routers:
              - name: r
                interfaces: [{ network: lab }, { network: lab }]
                acl: [{ from: lab, to: wan, allow: [] }]
            """,
            "undeclared network",
            id="acl-dangling-network",
        ),
        pytest.param(
            "attacker: { host: nosuch, entry: assumed-breach }",
            "undeclared host",
            id="dangling-attacker-host",
        ),
        pytest.param(
            """
            attacker:
              host: web
              interfaces: [{ network: lab }]
              entry: assumed-breach
            """,
            "must not also declare",
            id="attacker-host-and-interfaces",
        ),
        pytest.param(
            "attacker: { entry: external }",
            "host= or at least one interface",
            id="attacker-without-foothold",
        ),
    ],
)
def test_invalid_specs_rejected(overrides: str, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        RangeSpec.model_validate(_with(overrides))


def test_bad_schema_version_rejected() -> None:
    data = _with("{}")
    data["range"]["schema_version"] = "0.2"
    with pytest.raises(ValidationError, match="schema_version"):
        RangeSpec.model_validate(data)


@pytest.mark.parametrize("entry", ["tcp/5432", "udp/53", "tcp/1-65535"])
def test_valid_allow_entries(entry: str) -> None:
    data = _with(
        f"""
        routers:
          - name: r
            interfaces: [{{ network: lab }}, {{ network: lab }}]
            acl: [{{ from: lab, to: lab, allow: [{entry}] }}]
        """
    )
    RangeSpec.model_validate(data)


def test_json_schema_exports_aliases() -> None:
    schema = range_json_schema()
    assert "range" in schema["properties"]
    acl_rule = schema["$defs"]["AclRule"]
    assert "from" in acl_rule["properties"]
