# Spike: Active Directory domain under the range container

*Settles queued confirmation spike 1 from [architecture.md](../../inspect-ranges/architecture.md): can an AD domain be built through our pipeline (golden-image clones, qemu-ga control, compiled-style networking), and what does it cost? One Server 2022 DC promoted to a forest root (`range.lab`) plus one member joined, both cloned from the same golden image, orchestrated entirely over qemu-ga as SYSTEM. Run on the m6i.metal devbox, 2026-10-03. `./run.sh` reproduces everything (expects the two ISOs from the [win-guest](../win-guest/README.md) cache); `./run.sh down` tears down.*

## Verdict

**AD works through the pipeline, with one hard requirement surfaced: clones must be sysprep-generalized before they can join a domain whose DC came from the same golden image.** Windows refuses the join outright ("the SID of the domain you attempted to join was identical to the SID of this machine"), because a new forest's domain SID is derived from the first DC's machine SID. After `sysprep /generalize` on the member (208 s, scripted, unattended), promotion, join, DNS through the DC, and Kerberos auth as a domain user all work first try. The converged pair saves in 19 s and restores in 3 s with the secure channel intact, which confirms the key architectural bet: AD convergence is a range-build-time cost, not a per-sample cost.

## Measurements (metal, final clean run; wall-clock)

| What | Result |
|---|---|
| Boot both clones from golden overlay, agents responsive | **8 s** |
| Machine SIDs of the two clones | identical (no sysprep), as expected |
| DC promotion: AD DS feature + `Install-ADDSForest` | **106 s** (plus reboot) |
| Promotion total, start to AD DS + DNS SRV answering | **177 s** (post-reboot convergence 6–42 s across runs) |
| Domain join with duplicate machine SID | **refused** by Windows with an explicit sysprep error |
| `sysprep /generalize /oobe` to specialized clone with new SID | **208 s** (unattended, via a generated unattend.xml; qemu-ga survives it) |
| Member join post-sysprep, start to rebooted into domain | **20 s** |
| Verification | secure channel OK; DC resolves `WS01.range.lab`; SMB auth from member as a created domain user OK |
| `virsh save` both VMs (2 × 4 GB) / restore both + clock fix | **19 s / 3 s**; secure channel still OK after restore |
| Total, boot clones to verified domain (incl. the refusal detour) | **554 s** |

## Consequences for the design

1. **Sysprep is mandatory for AD images, not hygiene.** Golden images destined for domain membership (DC or member) must be generalized; the per-clone specialize cost (~3.5 min on first boot) is paid once per range build. Non-AD Windows targets keep the 6.5 s golden-overlay boots. This likely means two Windows golden flavors (plain and generalized), decided per host role at compile time.
2. **AD ranges fit the per-sample fresh-boot model via memory snapshots.** Specialize + promote + join is minutes, but it happens once when the range image set is built; a converged domain restores from snapshot in seconds with Kerberos intact (clock pushed via `guest-set-time` on restore, as the provider will do). The snapshot-after-converged idea from win-guest consequence 3 is now demonstrated, not hypothesized.
3. **Cross-host provisioning ordering is real but mild.** The DC must be promoted and answering before members join; polling `Get-ADDomain` + the `_ldap._tcp` SRV record over qemu-ga was sufficient (convergence 6–42 s after the promotion reboot). The provider needs a dependency step between hosts, not a full orchestration framework.
4. **DNS delegation works as compiled.** Members simply get the DC as their DNS server in their static network config (what the compiler would bake); name resolution, SRV discovery, and Kerberos all flow through it. Still open for mixed ranges: Linux guests resolving the AD zone (dnsmasq forward rule, unwired).
5. **qemu-ga carried the whole thing as SYSTEM**: feature install, forest promotion, sysprep, joins, roughly ten reboots, zero channel flakes this run (the ~5–7 % flake caveat from guest-exec-lessons stands). Two harness lessons for the provider: detect reboots by `LastBootUpTime` change, never by watching the agent drop (a fast reboot completes between orchestration steps); launch commands that end in a reboot of their own (sysprep) detached, since the exec session dies with the reboot.
6. **libvirt-managed networks do not work in the unprivileged container** (`net-start` writes under `/proc/sys`, which Docker mounts read-only). Plain kernel bridges plus `--network bridge=` work and are what the compiled pipeline uses anyway; the container needed `iproute2` added.

## Files

- `run.sh` — full orchestration: golden install (if missing), boot clones, configure, promote, the expected duplicate-SID refusal, sysprep, join, verify, save/restore
- `ga.py` — qemu-ga driver: PowerShell via `-EncodedCommand`, exec-status polling, `LastBootUpTime` reboot barrier, `guest-set-time`
- `assets/boot-ad.sh` — kernel bridge + two clones from the golden image
- `assets/autounattend.xml`, `assets/install.sh` — golden image build, copied from win-guest
- `tmp/run-final-clean.log` — the final clean run's output (CLIXML progress noise stripped)
