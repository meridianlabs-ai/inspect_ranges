# Spike: Windows Server guest under the range container

*Settles the Windows questions gating the architecture document (handoff §13 experiment 2, plus the exec-plane assumption from [agent-containment](../../inspect-ranges/agent-containment.md)): does Windows Server install and run under our libvirt-in-Docker stack on metal, what are the boot/snapshot economics, and — the buried assumption — does virtio-vsock work in Windows guests? Run on the m6i.metal devbox, 2026-10-01. `./run.sh` reproduces everything (expects the two ISOs in the image cache; sources below); `./run.sh down` tears down.*

## Verdict

Windows under this stack is **unexpectedly cheap** — 3-minute unattended install, 6.5 s boot-to-exec, 1.4 s snapshot restore — but **the shipped virtio-win package leaves the vsock device unbound**, confirmed empirically. (Upstream maintains a `viosock` driver this spike did not evaluate; its packaging/signing status is a queued investigation — this spike establishes only that a standard guest-tools install does not provide vsock.) The exec-plane claim becomes: **vsock for the agent and Linux targets; QEMU guest agent for Windows targets.** qemu-ga exec is fine; its file plane is ~three orders of magnitude slower than vsock, so bulk transfer to Windows guests needs the ISO/disk-hotplug fallback.

## Measurements (metal, EBS gp3, Server 2022 Standard Core eval)

| What | Result |
|---|---|
| Unattended install, ISO → finalized golden image | **189 s** (WinPE + apply + specialize + OOBE + virtio-win guest tools + self-shutdown) |
| Boot from golden overlay → qemu-ga responsive | **6.5 s** |
| `guest-exec` (whoami/hostname as SYSTEM) | works; ~2 s round trip incl. status poll |
| virtio driver binding after guest-tools install | serial/balloon/SCSI **OK**; **vsock (`DEV_1053`): Error, no driver** — "PCI Simple Communications Controller" |
| qemu-ga file transfer (5 MB, 64 KB chunks) | **~0.6 MB/s** each way (vs ~400–700 MB/s over vsock to Linux guests) |
| `virsh save` (4 GB RAM → 1.16 GB state file) | **10.1 s** |
| `virsh restore` → ga responsive | **1.3 s + 0.1 s** (warm page cache; cold-from-EBS will be slower — gp3 baseline caveat in handoff §6 stands) |

## Consequences for the design

1. **The exec plane is split by guest OS, not unified.** Agent + Linux targets: vsock daemon (1.1 ms exec, ~400 MB/s files). Windows targets: qemu-ga (`guest-exec`/`guest-file-*`) — exec latency is acceptable for provisioning/scoring; the file plane is not for bulk. Amend the "one exec mechanism" phrasing in the decision records.
2. **Bulk transfer to Windows = ISO/disk hotplug** (the UK AISI Proxmox workaround), now promoted from fallback to the designated Windows bulk path.
3. **Memory snapshots are the Windows boot-storm answer**: 1.4 s restore vs 6.5 s boot vs minutes for AD service convergence (a DC's AD services need far longer than boot — snapshot-after-converged skips that entirely). Clock-jump caveats (Kerberos) from handoff §6 apply.
4. **The virsh-CLI transport caps qemu-ga payloads at ~64 KB raw per call** (Linux `MAX_ARG_STRLEN` on the JSON argument). The real provider must use the libvirt API (python-libvirt), not CLI shelling, for guest-agent traffic.
5. **Driver injection + unattended install work headless first-try** under the stack (viostor via `PnpCustomizationsWinPE` DriverPaths; `--boot hd,cdrom` + blank disk avoids the press-any-key prompt on BIOS). `virsh screenshot` through the container was the only debugging tool needed — validating the handoff §10 screenshot story.
6. Open handles leak across qemu-ga client crashes (`guest-file-open` with no close blocks reopening) — the provider's file ops need handle hygiene and crash-safe retry naming.

## ISO sources (not cached in-repo; eval licensing)

- Windows Server 2022 eval: `https://go.microsoft.com/fwlink/p/?LinkID=2195280&clcid=0x409&culture=en-us&country=US` → `$IMAGE_CACHE/ws2022-eval.iso`
- virtio-win: `https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso` → `$IMAGE_CACHE/virtio-win.iso`

## Files

- `assets/autounattend.xml` — BIOS/MBR, Standard Core (index 1), viostor in WinPE, guest tools + self-shutdown at first logon
- `assets/install.sh` — golden-image build inside the range container (3 CDROMs: install, virtio-win, generated unattend ISO)
- `assets/boot-test.sh` — overlay boot with vsock device (driver probe) + qemu-ga channel
- `assets/file-bench.py` — qemu-ga file throughput
- `run.sh` — install (one-time), boot timing, exec, vsock probe, file bench, save/restore
