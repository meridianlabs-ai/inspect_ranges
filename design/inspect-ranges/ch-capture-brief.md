# Cloud Hypervisor capture: slice brief

Status: executed (2026-11; this file was the slice's brief and stays as its record). Was parked in [attack-box-v1](attack-box-v1.md) ("Attacker provisioning", decision 2) and [agent-containment](agent-containment.md) ("The attack box runs on Cloud Hypervisor by default"). This brief is self-contained: it names the blocker, the fix shape, the scope boundary, the test surfaces, and the proof bar.

## Goal

Lift the `cloud-hypervisor-content-unsupported` refusal by making the build's capture phase work for guests running under the cloud-hypervisor VMM. The refusal fires in two places in `src/inspect_ranges/_compiler/plan.py`: for hosts and routers declaring any content section (around line 369), and for a provisioned attack box (around line 433, where CH is the default and the hint names `vmm: qemu` as the fix). One mechanism lifts all three guest kinds at once.

## What already works

The capture phase is quiesce (scrub, poweroff, wait for shutoff) then disk copy. Almost all of it is already VMM-agnostic:

- **Convergence and quiesce run over the channel.** `scrub_guest` and `shutdown_guest` (`src/inspect_ranges/_build/capture.py`, lines 109 and 206) dial `VsockTransport(cids, hybrid_sockets=...)`, and `HybridSockets` is threaded through every build-side channel (recipes, settle, verify, capture, behavioral; see `_build/orchestrate.py:217`). Exec over CH's hybrid vsock is live-proven (`design/spikes/ch-vmm/`, checks C3/C4) and carries the vulhub battery from a CH attack box.
- **The disk copy is format-level, not VMM-level.** CH and qemu guests share the identical overlay chain: `qemu-img create -f qcow2 -b /images/<image> /scratch/<name>.qcow2` (`_runtime/up.py:393`). `capture_guest` does `docker cp` of that overlay plus `qemu-img rebase -u` onto the golden (`capture.py:342-345`), both of which work unchanged for a CH guest, and CH boots the captured realized image because it already runs with `backing_files=on`.
- **Console, readiness, identity guard, settle gate** need nothing: CH writes `/scratch/console/<name>.log` via `--serial file=`, and the rest is channel-based.

## The one blocker

`wait_shutoff` (`capture.py:246`) polls `docker exec <project>-range-1 virsh --connect qemu:///system domstate <guest>` every 2 s until the state contains "shut off" (120 s bound, 300 s for Windows). A CH guest is never a libvirt domain, so the poll can only burn the full timeout and fail the build. This is the entire reason the refusal exists.

## Fix shape

A CH shutoff wait keyed on the VMM pid, inverting the probe that `vmm_liveness` already runs (`_runtime/up.py:667`). The boot script launches CH through an exec chain and writes the CH pid itself to `/scratch/ch/<name>.pid` (`up.py:510`); liveness reads that pidfile and requires the `cloud-hyperviso` prefix in `/proc/<pid>/comm` (the 15-char comm truncation), because a bare `kill -0` reads alive-when-dead after pid recycling. Shutoff is the negation: the pidfile's process is gone, or its comm no longer matches. After the in-guest poweroff completes, the CH process exits on its own; there is no VMM control socket to consult (the range image ships no `ch-remote`, and the launch passes no `--api-socket`), so the pid is the authoritative signal.

Design points the slice must handle:

1. **Pid-exit is weaker than virsh's "shut off".** Libvirt's state implies a defined domain that stopped; a missing pid cannot distinguish a clean poweroff from a VMM crash or an OOM kill. The available tiebreakers are the VMM's own log (`/scratch/ch/<name>.log`, stdout/stderr of the launch) and the serial log. The wait should fold a tail of the VMM log into its failure diagnosis the same way `wait_shutoff` folds `shutdown_diagnosis` today, and the success path should tolerate a pid that exited before the first poll (the poweroff can win the race).
2. **Container resolution.** `wait_shutoff` derives the container name as `{project}-range-1`; `vmm_liveness` resolves the range service by compose labels instead, because capture and probe sidecars share the project label. The CH wait should follow the label resolution, and unifying the qemu wait onto it is in scope if it stays small.
3. **Dispatch at the quiesce seam.** `_quiesce_guest` (`orchestrate.py:256`) hardwires `default_capture_runner` and picks the timeout; it must learn which wait to run. The plan already carries each guest's VMM (the refusal reads it), so thread the guest's planned VMM (or the chosen wait) into the quiesce call rather than re-deriving it.
4. **Guest-name hygiene.** `vmm_liveness` gates names through `_SAFE_NAME_RE` before interpolating into the bash probe; the CH wait interpolates the same way and must keep the gate.

## Refusal lift and text sweep

Removing the refusal is part of the slice, not a follow-up: delete or narrow both `plan.py` sites, and update the text that states the limitation: the `Attacker.provisioning` docstring (`src/inspect_ranges/types.py`, around line 1031), `docs/security.qmd`, `docs/guests.qmd`, `docs/building.qmd` (the capture step description), and the two design records named at the top (amend, do not rewrite history: state that the slice landed and when). The docs tests pin refusal codes appearing in the qmd files, so stale text fails the suite.

Compatibility: lifting a refusal moves no spec hashes. A range that newly declares CH content lands behind `range-not-built`, by design. The neighbouring CH refusals are explicitly out of scope: `opaque-vmm-not-supported`, `hardware-vmm-not-supported`, `cloud-hypervisor-cpu-model`, and `windows-vmm-not-supported` all stay (Windows cannot run on CH regardless). Windows golden derivation (`winimage.py`) is untouched.

## Test surfaces

- `tests/test_build_capture.py`: the existing `wait_shutoff` timeout test (fake runner, asserts the diagnosis folding) is the model for the CH wait's unit tests: clean exit, pid recycled (comm mismatch reads as shutoff), pidfile missing at first poll, VMM still running at deadline with the log tail in the error.
- `tests/test_updown.py` (the `vmm_liveness` tests near line 2000): the `bash_runner_factory` harness already simulates the mixed virsh/pidfile probe and is the closest model for the new wait's probe tests.
- `tests/test_cloud_hypervisor.py`: the two refusal tests (planning refusal for CH content, `vmm: qemu` required on the provisioned attacker) invert into "plans clean"; the boot-script test already pins the pidfile write the wait depends on.
- `tests/test_build_orchestrate.py`: the quiesce/capture seams, extended for the VMM dispatch.

## Proof bar

House standard: two fresh-context reviews (mid-slice and full-diff pre-PR), full suite, and a live end-to-end proof on a devbox. The live proof should build a range with a CH content host and a provisioned CH attacker (no `vmm: qemu` declared): converge over hybrid vsock, capture, cached rebuild as the no-op, boot the realized image with the readiness identity guard passing, and read the recipe's marker back from the captured image. Add a capture check to the spike battery (`design/spikes/ch-vmm/`, as C9). Prove the failure path too: kill the CH VMM mid-quiesce and show the build error carries the VMM log tail rather than a bare timeout.
