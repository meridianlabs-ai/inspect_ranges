# Spike: minimal QEMU device model (explicitly compiled, per role)

*Executes [agent-containment](../../inspect-ranges/agent-containment.md) hardening backlog item 3's remaining half: the escape-surface argument says "the practical surface is the configured device model", but the spike guests carried virt-install defaults (USB controller, memballoon, SATA cdrom, auto-added qemu-ga channel). This spike makes the claim true: the compiler-side artifact is explicit domain XML — every functional device declared, no tool default deciding the attack surface — in two per-role profiles, run under the full [hardened-container](../hardened-container/README.md) profile to prove the envelopes compose. Run on the m6i.metal devbox, 2026-10-04. `./run.sh` reproduces (needs `../net-compile/run.sh` artifacts once); `./run.sh down` tears down.*

## Verdict

**The minimal device model works with zero function lost and a measurable surface cut, at slightly better boot time.** The agent guest's visible PCI surface dropped **25 → 15 devices**; the full 4-VM range boots from explicit XML, provisions via a virtio-carried cloud-init seed, passes all nine ACL/isolation checks, runs the exec/file plane at full speed, and survives `virsh save`/`restore` under the minimal device set — in **44.1 s** to enforced-ready vs ~50 s with virt-install defaults, under the hardened container profile throughout.

## Profiles (emitted by `gen-xml.py`)

- **strict** (agent, db, router): virtio disk ×2 (root overlay + cloud-init seed as a read-only virtio disk, replacing the SATA cdrom), virtio NIC(s), vsock, serial console, virtio-rng. Explicitly suppressed: `<memballoon model='none'/>`, `<controller type='usb' model='none'/>`. Not present at all: video, graphics, tablet, cdrom, and — notable — **no qemu-ga channel** (virt-install auto-adds one; Linux guests are vsock-only, so it's gone).
- **target-standard** (web): strict plus `<video model='virtio'/>` + local VNC, demonstrating per-role emission for scenarios that need screenshots/console imagery.

## Measured surface change (from inside the guest, `/sys/bus/pci`)

| | baseline (virt-install defaults) | strict profile |
|---|---|---|
| guest-visible PCI devices | 25 | **15** |
| removed | — | XHCI USB controller, memballoon, virtio-serial (qemu-ga channel), 8 superfluous PCIe root ports |
| added | — | one virtio-blk (the seed disk that replaced the SATA cdrom) |

Host-side XML: 18 controllers → 9; the `<channel>` (guest agent) element gone. What remains and why: PS/2 keyboard/mouse (`i8042` is q35 machine-inherent), the iTCO `<watchdog>` (chipset-inherent; libvirt surfaces it), `<audio type='none'/>` (a backend declaration, no guest-visible hardware), the q35 built-in AHCI controller (no media attached). These are machine-architecture facts, not optional devices; moving to a slimmer machine type would be the next increment if ever justified.

## What the battery proved under the minimal model

- **cloud-init provisioning from a virtio seed disk works** (NoCloud finds the labeled iso9660 filesystem on `vdb`); range fully enforced in 44.1 s.
- **T1–T9 all pass** (same-segment, routed/allowed, default-deny, asymmetry, L2 isolation, gateway, host-netns invisibility, netns invariants).
- **exec/file plane unaffected**: 1 MB round trip at ~350/460 MB/s over vsock.
- **virtio-rng present, no entropy starvation** (`/dev/hwrng` bound; the classic non-obvious slow-boot failure this device preempts).
- **save/restore works with the minimal device set** (the snapshot embeds its device model; consistency verified by restore + exec).
- **Teardown clean under the hardened profile** (the `KILL`-capability path).

No ease-on-failure entries were needed: nothing broke. The one deliberate semantic change is the dropped qemu-ga channel on Linux guests — acceptable because the control plane is vsock and qemu-ga is build-time tooling for Windows images only ([vsockd-win](../vsockd-win/README.md)).

## Consequences for the design

1. **Backlog item 3 is now fully demonstrated** (device minimization here; `seccomp_sandbox` and the container floor in hardened-container). The escape-surface sentence — the practical attack surface is the configured device model, minimal and explicitly declared — is a measured fact: for the agent VM, the virtio attack surface is disk, net, vsock, rng, serial, and nothing else.
2. **The production compiler emits domain XML, not virt-install invocations.** `gen-xml.py` is the template: per-role profiles chosen at compile time (strict by default; video only where the scenario declares it), every device explicit, machine-inherent residue documented.
3. **Profiles compose**: minimal devices + hardened container + non-root QEMU + QEMU sandbox all ran together with no interaction effects and no measured cost.

## Files

- `gen-xml.py` — allocation.json → explicit per-role domain XML + boot script (the compiler template)
- `compose.yaml` — the hardened-container profile reused verbatim
- `run.sh` — baseline capture, minimal-XML boot, surface diff, T1–T9, exec/file, rng, save/restore, teardown
- `tmp/run1.log`, `tmp/{baseline,agent}.xml`, `tmp/{baseline,agent}-pci.txt` — artifacts from the clean first-try run
