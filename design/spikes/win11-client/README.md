# Spike battery: win11-client (windows11-client-v1, slice 1)

*The Windows 11 client golden and clone: `images derive-windows --os 11` installs the sysprep'd client golden from digest-pinned user-supplied media under the contract setup verifies (q35, the MS-key secure loader with SMM, an emulated TPM 2.0, a GPT/ESP layout, w11 virtio drivers, Pro by index with the documented edition-selection key; boot-prompt keys gated on the install cdrom's read counter, the client OOBE wizard skipped), re-deriving is a cache hit on the full key (which carries the OS variant); then a range with one Windows 11 host (`hardware: { firmware: uefi-secure, tpm: true }`, the plan gate's required shape) and a Linux attacker renders and boots on the production pipeline: the clone specializes from the render-emitted unattend seed, readiness is daemon-only, exec answers as SYSTEM over vsock, and the CONTRACT is proven from inside the guest (`Confirm-SecureBootUEFI` true, `Get-Tpm` ready — both need the elevated session, which SYSTEM is). L3 proven outbound (the Windows Firewall drops inbound ICMP), teardown clean. Windows artifacts are LOCAL ONLY (recipes-not-images, the ratified posture). Serializes on `/tmp/inspect-ranges-battery.lock` and the host-global win-install lock; CID band 4160.*

*Reproduce: `./run.sh` (Win11 install ISO + virtio-win.iso + the noble vendor in the shared cache, `vhost_vsock`; ~50 min, dominated by the unattended client install). `./run.sh down` tears down.*

## Checks

1. **W11-1** the client golden installs from pinned media (`--os 11`); re-deriving with the same pins is a cache hit; the sidecar records `kind: installed`.
2. **W11-2** render accepts the Windows 11 host only with the declared hardware contract (the gate is unit-pinned; here the contract shape boots), and `up` reaches readiness on the daemon alone.
3. **W11-3** the specialize seed applied (hostname, MAC-keyed static address), exec is SYSTEM, and the contract holds in-guest: Secure Boot verified from the guest's own firmware view, the TPM ready, the edition Pro. L3 proven outbound across the segment.
4. **W11-4** teardown leaves nothing.

## Files

- `run.sh`: derive, boot, prove, teardown under the battery lock.
