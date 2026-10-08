"""Spike compiler: a validated `RangeSpec` -> runtime artifacts for the range container.

Consumes the real schema (`inspect_ranges.schema`) — this spike closes the loop
proving the v0.1 models are consumable by a compiler. Emits per-VM cloud-init
seeds (static addressing), bridges, vsock CID allocation, and the boot script.
"""

import json
from pathlib import Path
from typing import Any

import yaml

from inspect_ranges.schema import RangeSpec

FIRST_CID = 3


def bridge(network: str) -> str:
    return f"br-{network}"[:15]


def mac(index: int) -> str:
    return f"52:54:00:90:00:{index:02x}"


def compile_range(spec: RangeSpec, render: Path) -> dict[str, Any]:
    """Render runtime artifacts into `render`; return the allocation map."""
    networks = {n.name: n for n in spec.networks}
    guests: list[dict[str, Any]] = []

    def add(name: str, image: str | None, interfaces: Any) -> None:
        guests.append(
            {
                "name": name,
                "image": image or "noble-e2e",
                "cid": FIRST_CID + len(guests),
                "interfaces": [
                    {
                        "network": i.network,
                        "ip": str(i.ip) if i.ip else None,
                        "prefix": networks[i.network].cidr.prefixlen,
                        "mac": mac(len(guests) * 4 + k),
                    }
                    for k, i in enumerate(interfaces)
                ],
            }
        )

    for host in spec.hosts:
        add(host.name, host.image, host.interfaces)
    if spec.attacker.host is None:
        add(spec.attacker.name, spec.attacker.image, spec.attacker.interfaces or [])

    render.mkdir(parents=True, exist_ok=True)
    render.joinpath("bridges.txt").write_text(
        "".join(f"{bridge(name)}\n" for name in networks)
    )
    render.joinpath("range-netns.nft").write_text(
        "flush ruleset\n"
        "table inet rangehost {\n"
        "  chain forward { type filter hook forward priority 0; policy drop; }\n"
        "}\n"
    )
    boot = ["#!/bin/bash", "set -euxo pipefail"]
    for guest in guests:
        d = render / "vms" / guest["name"]
        d.mkdir(parents=True, exist_ok=True)
        d.joinpath("meta-data").write_text(
            f"instance-id: {spec.meta.name}-{guest['name']}\nlocal-hostname: {guest['name']}\n"
        )
        d.joinpath("user-data").write_text(f"#cloud-config\nhostname: {guest['name']}\n")
        ethernets = {
            f"{i['network']}0": {
                "match": {"macaddress": i["mac"]},
                "set-name": f"{i['network']}0",
                "addresses": [f"{i['ip']}/{i['prefix']}"],
            }
            for i in guest["interfaces"]
            if i["ip"]
        }
        d.joinpath("network-config").write_text(
            yaml.safe_dump({"version": 2, "ethernets": ethernets}, sort_keys=False)
        )
        name = guest["name"]
        nets = " ".join(
            f"--network bridge={bridge(i['network'])},model=virtio,mac={i['mac']}"
            for i in guest["interfaces"]
        )
        boot += [
            f"qemu-img create -f qcow2 -F qcow2 -b /images/{guest['image']}.qcow2 /scratch/{name}.qcow2 10G",
            f"cloud-localds -N /render/vms/{name}/network-config /scratch/{name}-seed.iso "
            f"/render/vms/{name}/user-data /render/vms/{name}/meta-data",
            f"virt-install --connect qemu:///system --name {name} "
            "--memory 1024 --vcpus 1 --cpu host-passthrough "
            f"--disk path=/scratch/{name}.qcow2,format=qcow2,bus=virtio "
            f"--disk path=/scratch/{name}-seed.iso,device=cdrom "
            f"{nets} --vsock cid.address={guest['cid']} "
            "--osinfo ubuntu24.04 --import --graphics none --noautoconsole",
        ]
    render.joinpath("boot-vms.sh").write_text("\n".join(boot) + "\n")
    allocation = {g["name"]: g for g in guests}
    render.joinpath("allocation.json").write_text(json.dumps(allocation, indent=2))
    return allocation
