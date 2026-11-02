#!/bin/bash
# windows11-client-v1 slice 1 battery: the Windows 11 client golden and clone.
# `images derive-windows --os 11` installs the sysprep'd client golden under
# the contract setup verifies (secure boot + SMM + TPM, GPT/ESP, w11 drivers,
# OOBE wizard skipped), then a range with one Windows 11 host (the declared
# hardware contract) and a Linux attacker boots on the PRODUCTION pipeline:
# daemon readiness, SYSTEM exec, and the contract proven from inside the
# guest. Usage: ./run.sh [down]. CID band 4160.
set -euo pipefail
cd "$(dirname "$0")"
SPIKE="$PWD"
ROOT="$(cd ../../.. && pwd)"

WIN_ISO="${WIN_ISO:-$HOME/.cache/inspect-ranges/images/Win11.iso}"
VIRTIO_ISO="${VIRTIO_ISO:-$HOME/.cache/inspect-ranges/images/virtio-win.iso}"
NOBLE="${NOBLE:-$HOME/.cache/inspect-ranges/images/noble-server-cloudimg-amd64.img}"
export XDG_STATE_HOME="$SPIKE/tmp/state"
# the published range image predates swtpm (it ships with the release that
# carries this branch); the battery builds and uses the local image
unset INSPECT_RANGES_RANGE_IMAGE
IR="uv run inspect-ranges"
CACHE="$SPIKE/tmp/cache"

if [[ "${1:-}" == "down" ]]; then
  (cd "$ROOT" && $IR down --all) || true
  exit 0
fi

grep -q vhost_vsock /proc/modules || { echo "need: sudo modprobe vhost_vsock"; exit 1; }
[[ -f "$WIN_ISO" && -f "$VIRTIO_ISO" && -f "$NOBLE" ]] || { echo "missing media"; exit 1; }

PASS=0; FAIL=0
ok()  { echo "PASS  $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL  $1"; FAIL=$((FAIL+1)); }

exec 9>/tmp/inspect-ranges-battery.lock
flock 9
cd "$ROOT"
$IR down --all >/dev/null 2>&1 || true
rm -rf "$SPIKE/tmp" && mkdir -p "$SPIKE/tmp"

echo "=== W11-1 install the Windows 11 client golden from pinned media ==="
DB_OUT=$($IR daemon-bundle -o "$SPIKE/tmp/artifacts")
DAEMON_SHA=$(echo "$DB_OUT" | grep -o 'bundle sha256:[0-9a-f]*' | cut -d: -f2)
WIN_SHA=$(sha256sum "$WIN_ISO" | cut -d' ' -f1)
VIRTIO_SHA=$(sha256sum "$VIRTIO_ISO" | cut -d' ' -f1)
if $IR images derive-windows "$WIN_ISO" --sha256 "$WIN_SHA" \
    --virtio-iso "$VIRTIO_ISO" --virtio-sha256 "$VIRTIO_SHA" --os 11 \
    --image-cache "$CACHE" --daemon-bundle "$SPIKE/tmp/artifacts" \
    --daemon-sha256 "$DAEMON_SHA" >"$SPIKE/tmp/w1.txt" 2>&1; then
  grep -q "installed: windows-11.qcow2" "$SPIKE/tmp/w1.txt" \
    && ok "W11-1 the client golden installed (secure boot + TPM installer, sysprep'd, daemon baked)" \
    || { bad "W11-1 output"; cat "$SPIKE/tmp/w1.txt"; }
else
  bad "W11-1 derive-windows --os 11"; tail -5 "$SPIKE/tmp/w1.txt"; exit 1
fi
grep -q '"kind": "installed"' "$CACHE/windows-11.json" \
  && ok "W11-1b the sidecar records kind=installed explicitly" \
  || bad "W11-1b sidecar kind"
$IR images derive-windows "$WIN_ISO" --sha256 "$WIN_SHA" \
    --virtio-iso "$VIRTIO_ISO" --virtio-sha256 "$VIRTIO_SHA" --os 11 \
    --image-cache "$CACHE" --daemon-bundle "$SPIKE/tmp/artifacts" \
    --daemon-sha256 "$DAEMON_SHA" >"$SPIKE/tmp/w1b.txt" 2>&1 \
  && grep -q "cache hit" "$SPIKE/tmp/w1b.txt" \
  && ok "W11-1c re-deriving is a cache hit (the key carries the OS variant)" \
  || { bad "W11-1c idempotence"; tail -3 "$SPIKE/tmp/w1b.txt"; }

echo "=== W11-2 the Windows 11 clone boots on the production pipeline ==="
$IR images derive "$NOBLE" --sha256 "$(sha256sum "$NOBLE" | cut -d' ' -f1)" --name ubuntu-noble \
  --image-cache "$CACHE" --daemon-bundle "$SPIKE/tmp/artifacts" --daemon-sha256 "$DAEMON_SHA" >/dev/null
mkdir -p "$SPIKE/tmp/range"
cat > "$SPIKE/tmp/range/range.yaml" <<'SPEC'
range:
  name: win11-slice1
  schema_version: "0.3"
  description: one windows 11 client and a linux attacker, the slice-1 proof
networks:
  - name: corp
    cidr: 10.22.0.0/24
    mode: isolated
hosts:
  - name: client
    os: { type: windows, version: "11" }
    image: windows-11
    hardware: { firmware: uefi-secure, tpm: true }
    resources: { cpus: 2, memory_mb: 4096 }
    interfaces: [{ network: corp, ip: 10.22.0.10 }]
attacker:
  image: ubuntu-noble
  interfaces: [{ network: corp }]
  entry: external
SPEC
$IR render "$SPIKE/tmp/range" -o "$SPIKE/tmp/bundle" --image-cache "$CACHE" --cid-base 4160 >/dev/null 2>&1 \
  && ok "W11-2 render succeeds for the contract shape (gate + domain pins are unit-tested)" || { bad "W11-2 render"; exit 1; }
if $IR up "$SPIKE/tmp/bundle" --image-cache "$CACHE" --readiness-timeout 600 >"$SPIKE/tmp/w2.txt" 2>&1; then
  ok "W11-2b up: the clone specialized and the daemon answered (daemon readiness)"
else
  bad "W11-2b up"; tail -8 "$SPIKE/tmp/w2.txt"; exit 1
fi

echo "=== W11-3 seed applied, SYSTEM exec, the contract in-guest ==="
BOOT="$SPIKE/tmp/bundle/boot.json"
PROJECT=$(docker ps --format '{{.Names}}' | grep -E '^ir-win11-slice1-' | head -1 | sed 's/-range-1$//')
CHEXEC="uv run python design/spikes/_shared/chexec.py --boot $BOOT --project $PROJECT --guest client --shell cmd exec"
HOSTOUT=$($CHEXEC 'hostname' 2>&1 | tail -1 | tr -d '\r' | tr '[:upper:]' '[:lower:]')
[[ "$HOSTOUT" == "client" ]] && ok "W11-3 the per-boot unattend set the hostname ($HOSTOUT)" || bad "W11-3 hostname (got: $HOSTOUT)"
IPOUT=$($CHEXEC 'ipconfig' 2>&1 | grep -c "10.22.0.10" || true)
[[ "$IPOUT" -ge 1 ]] && ok "W11-3b the MAC-keyed static address applied (10.22.0.10)" || bad "W11-3b static ip"
WHO=$($CHEXEC 'whoami' 2>&1 | tail -1 | tr -d '\r')
[[ "$WHO" == *"system"* ]] && ok "W11-3c exec runs as SYSTEM over vsock ($WHO)" || bad "W11-3c whoami (got: $WHO)"
# the contract from the guest's own view (both probes need the elevated
# session, which SYSTEM is); pipe-free commands (cmd steals | before
# powershell sees it)
SB=$($CHEXEC 'powershell -NoProfile -Command Confirm-SecureBootUEFI' 2>&1 | tail -1 | tr -d ' \r')
[[ "$SB" == "True" ]] && ok "W11-3d Secure Boot verified in-guest (Confirm-SecureBootUEFI)" || bad "W11-3d secure boot (got: $SB)"
TPM=$($CHEXEC 'powershell -NoProfile -Command (Get-Tpm).TpmReady' 2>&1 | tail -1 | tr -d ' \r')
[[ "$TPM" == "True" ]] && ok "W11-3e the TPM is ready in-guest (Get-Tpm)" || bad "W11-3e tpm (got: $TPM)"
EDITION=$($CHEXEC 'powershell -NoProfile -Command (Get-CimInstance Win32_OperatingSystem).Caption' 2>&1 | tail -1 | tr -d '\r')
[[ "$EDITION" == *"Windows 11 Pro"* ]] && ok "W11-3f the selected edition installed ($EDITION)" || bad "W11-3f edition (got: $EDITION)"
ATT_IP=$(python3 -c "
import json
plan = json.load(open('$SPIKE/tmp/bundle/plan.json'))
guest = next(g for g in plan['guests'] if g['name'] == 'attacker')
print(guest['interfaces'][0]['ip'])
")
PING=$($CHEXEC "ping -n 2 -w 3000 $ATT_IP >nul && echo L3-OK || echo L3-DEAD" 2>&1 | tail -1 | tr -d ' \r')
[[ "$PING" == "L3-OK" ]] && ok "W11-3g outbound L3 across the segment (client pinged the attacker at $ATT_IP)" || bad "W11-3g L3 (got: $PING)"

$IR down --all >/dev/null 2>&1 || true
docker ps --format '{{.Names}}' | grep -q '^ir-win11-slice1-' && bad "W11-4 teardown left containers" || ok "W11-4 teardown clean"
echo
echo "$PASS passed, $FAIL failed"
exit $((FAIL > 0))
