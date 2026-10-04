# Spike: Windows vsock (viosock) — bounded investigation

*Settles [external review](../../inspect-ranges/external-review.md) finding 8. The win-guest spike observed the vsock PCI device unbound after a full virtio-win guest-tools install, and the records over-generalized that to "no Windows vsock driver exists." This spike establishes the actual state of upstream `viosock`: packaging, signing, installation, and whether it carries real traffic. Run on the m6i.metal devbox, 2026-10-04. `./run.sh` reproduces everything (expects the two ISOs from the win-guest cache); `./run.sh down` tears down.*

## Verdict

**Windows vsock works, with production signing, from the ISO we already ship.** The stable virtio-win ISO (0.1.302) contains `viosock` drivers for 2k16/2k19/2k22/2k25/w10/w11 (amd64 + ARM64), **WHQL-signed** ("Microsoft Windows Hardware Compatibility Publisher" — verified with osslsigncode), plus a Winsock service provider (`viosocklib`) and support binaries (`viosockwspsvc.exe`, `vstbridge.exe`). The guest-tools MSI simply does not install it. One `pnputil /add-driver ... /install` later, the device binds (`OK — VirtIO Socket Driver`), the Winsock catalog gains "Virtio Vsock STREAM" (address family 40), and **a native Windows listener exchanged stream data with a Linux host client over vsock** (`hello-from-host` → `echo:hello-from-host`, both directions verified).

## What was demonstrated

| Step | Result |
|---|---|
| Driver provenance | `viosock/2k22/amd64/{viosock.sys,.inf,.cat}` on stable ISO 0.1.302; `.sys` WHQL-signed (no test-signing mode needed) |
| Install | `pnputil /add-driver /install` from the mounted ISO, as SYSTEM over qemu-ga; no reboot required for binding |
| Binding | `DEV_1053`: `Error — PCI Simple Communications Controller` → `OK — VirtIO Socket Driver`; driver answers ioctls (reports its CID) |
| Winsock provider | `Virtio Vsock STREAM`, AF 40, registered by the driver install (no separate step) |
| Data path | Guest: .NET/Winsock listener on `VMADDR_CID_ANY:5000` (a ~20-line PowerShell `EndPoint` shim, `assets/listener.ps1`); host: Python `AF_VSOCK` connect, send, receive echo — bidirectional round trip verified |
| Dead end (noted) | `viosock-test.exe`'s raw `\??\Viosock` device path returns `STATUS_NOT_SUPPORTED` even version-matched — the supported interface is the Winsock provider, not the raw device |

## Consequences for the design

1. **The OS-split exec plane is no longer forced by platform reality.** The architecture's "vsock for Linux, qemu-ga + ISO hot-plug for Windows" rested on a driver-availability claim that is false as of virtio-win 0.1.302. Windows targets *can* join the same vsock control plane as Linux guests.
2. **Adoption cost is a daemon port, not infrastructure**: a Windows daemon speaking our exec/file protocol over AF-40 Winsock sockets (native or .NET; no Python dependency in guests), installed into the Windows golden image alongside the driver. The channel abstraction above the transport is unchanged by design.
3. **What this likely retires**: the ~0.6 MB/s qemu-ga file plane and the ISO hot-plug bulk path for Windows targets. Throughput over Windows vsock was not measured here (the PowerShell listener is not a benchmark); measure with the real daemon port before declaring numbers.
4. **What qemu-ga keeps**: image build and provisioning (it ships with guest-tools, works before our daemon exists in an image, and drove sysprep/promotion through reboots in the ad-domain spike).
5. **Still to verify before committing the port**: behavior across `virsh save`/`restore` (open sockets and the driver's reaction to a restore), the Windows daemon's user/privilege model, and sustained throughput. The decision stands as: default plan is to port the daemon and unify the control plane; qemu-ga remains the working fallback until the port passes `self_check`.

## Files

- `run.sh` — provenance listing, boot with vsock device, pnputil install, binding + catalog checks, listener/echo test (host side embedded)
- `assets/listener.ps1` — the native Winsock AF-40 listener (the `VSockEndPoint` shim is the piece a daemon port reuses)
- `ga.py`, `assets/{autounattend.xml,install.sh}`, `range/`, `compose.yaml` — copied from the checkpoint-clone/ad-domain machinery
- `tmp/run-final.log` — the clean scripted run
