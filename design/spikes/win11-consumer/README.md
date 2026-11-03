# Spike battery: win11-consumer (windows11-client-v1, slice 2)

*The Windows 11 client endpoint consumed the way deployments consume it: a content host (`provisioning` + `scheduled_activity`) on the slice-1 golden BUILDS through the production pipeline (the recipe runs as SYSTEM over the daemon: the declared low-privilege operator account, an on-demand SYSTEM maintenance task, the endpoint marker), the activity declaration verifies, the provisioned disk CAPTURES as a realized image, an unchanged rebuild is a cached no-op, and a consumer boots the captured client with the recipe's state intact. This is verification breadth on windows-ad machinery, not new substrate; the plant/trio surface deliberately waits for the first real client fixture (an attack box makes a trio meaningful), recorded in the design record. Serializes on `/tmp/inspect-ranges-battery.lock` and the host-global win-install lock; CID bands 4190 (build) / 4195 (consumer).*

*Reproduce: `./run.sh` (Win11 install ISO + virtio-win.iso + the noble vendor in the shared cache, `vhost_vsock`; ~80 min, dominated by the client golden install into the spike's clean cache). `./run.sh down` tears down.*

## Checks

1. **C1** the slice-1 golden installs into the battery's clean cache (`--os 11`).
2. **C2** the range builds: the recipe realizes as SYSTEM on the Windows 11 content host, the activity declaration verifies, and the provisioned disk captures as a realized image.
3. **C3** an unchanged rebuild is a cached no-op.
4. **C4** a consumer boots the captured client: the recipe's account, task, and marker are on the disk it booted, not re-provisioned.
5. **C5** teardown leaves nothing.

## Files

- `range/`: the consumer range (one Windows 11 content host + a Linux attacker), its recipe, and its activity script.
- `run.sh`: goldens, build, no-op, consumer boot, teardown under the battery lock.
