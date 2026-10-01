# Spike: vsock exec/file plane for VM agents

*Decides whether the agent can always be a VM (`kind: vm`) by testing the control plane that replaces `docker exec`: a NIC-less VM under the range container, driven purely over virtio-vsock by a small guest daemon (`guest/vsockd.py`). Run on the m6i.metal devbox, 2026-10-01. `./run.sh` reproduces everything (builds the derived image on first run); `./run.sh down` tears down. Follows the [l2-attach spike](../l2-attach/README.md); motivated by the always-`kind: vm` discussion in [agent-containment](../../inspect-ranges/agent-containment.md).*

## Verdict

**vsock removes the last performance argument for a container agent.** Exec round-trip is ~40× faster than `docker exec`, file transfer runs at hundreds of MB/s, and the VM needs *fewer* privileges than the container design (no NET_ADMIN anywhere, no veth helper, no NICs).

## Measurements

| What | Result |
|---|---|
| exec round-trip (median, 200 calls) | **1.1 ms** vsock vs **44.5 ms** `docker exec` (p95: 3.5 vs 47.2 ms) |
| exec_remote-style start+poll (2s cmd, 0.2s interval) | 2.01 s wall — polling overhead is noise |
| file inject (100 MB, host→guest) | 0.25 s (**398 MB/s**), sha256 verified |
| file extract (100 MB, guest→host) | 0.14 s (**696 MB/s**), sha256 verified |
| background process survives exec return | yes (daemon spawns with `start_new_session`) |
| loopback in NIC-less guest | `lo` UP with 127.0.0.1/8; TCP connect on it works (proxy injection OK) |
| compose up + VM boot → daemon ready | **9.6 s** (daemon baked into image, cloud-init disabled) |

The guest-agent 60 KiB limit and polling model are irrelevant on this path: vsock is a plain stream socket — blocking waits, no size limits.

## Architecture notes

- **The agent VM has zero NICs** in this spike and is fully controllable: exec, file transfer, polling — all over vsock, which is a hypervisor channel, not a network. In a real range the VM gets lab-segment NICs only; the control plane stays invisible to the range (no management NIC, nothing for in-range defenders to discover or firewall).
- **The range container needed no `cap_add` at all** for a vsock-only VM (just `/dev/kvm` + `/dev/vhost-vsock`, apparmor unconfined, `init: true`). Bridged NICs will bring back `NET_ADMIN` + `/dev/net/tun`, but the floor is remarkably low.
- **Daemon baked into a derived golden image** (`virt-customize --copy-in`, unit enabled by symlink, cloud-init and `systemd-networkd-wait-online` disabled) — the "standard agent image" story. First attempt used cloud-init `write_files`/`runcmd` instead: it worked but cost **+2 min**, because a NIC-less guest makes `systemd-networkd-wait-online` time out before cloud-init's final stage runs. Baked image: 9.6 s.
- **Host-side vsock needs `vhost_vsock` loaded** (`modprobe vhost_vsock`, persist via modules-load.d) — add to `doctor` and the devbox bootstrap. QEMU gets `/dev/vhost-vsock` as a device; the host-side client needs no device or privileges.
- **CIDs are host-kernel-global**, not namespaced: QEMU-in-container still allocates from the host's CID space, and any host process can connect to any guest CID. Two consequences: (1) CID allocation is an IPAM-style per-host resource (fine with one sample per instance; dev boxes running several ranges need deterministic allocation); (2) the guest daemon must check the peer CID (vsockd accepts only CID 2, the host) — and host-side, sample isolation of the vsock plane relies on one-sample-per-instance, since a container escape elsewhere on the host could reach guest CIDs.
- Protocol prototyped: one connection per request, JSON header line + raw byte stream for file ops; `exec` (blocking) and `start`/`poll` (exec_remote-style). The real daemon needs: timeout enforcement with process-tree kill, stderr/stdout separation on `poll`, output limits, write-stream fsync/rename semantics, and a `forward` op (vsock↔loopback) so injected proxies (e.g. a model relay on 127.0.0.1) can tunnel their upstream leg to the harness.

## Consequences for the design (if always-`kind: vm` is adopted)

- The veth attach helper — the only privileged component — disappears entirely (agent NICs are ordinary libvirt interfaces).
- One exec/file mechanism serves agent and targets; Inspect's `self_check` runs against the vsock path; the Docker-provider exec porting in [docker-provider-reuse](../../inspect-ranges/docker-provider-reuse.md) shrinks to the Docker-CLI-resilience and lifecycle pieces.
- Standard agent images (Kali + Debian) carry vsockd + QEMU guest agent; scaffold binaries (inspect_swe-style) are injected at ~400 MB/s via `write_file`.

## Files

- `guest/vsockd.py` — the in-guest daemon prototype (stdlib only)
- `host/client.py` — host-side client + benchmarks
- `range/`, `compose.yaml` — range container (libvirtd+QEMU, no network tooling, no caps)
- `assets/boot-vm.sh` — overlay → `virt-install --network none --vsock cid.address=3`
- `run.sh` — derived-image build (first run), boot, full benchmark battery
