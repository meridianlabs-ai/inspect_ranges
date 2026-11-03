#!/bin/bash
# windows11-client-v1 slice 2 battery: the Windows 11 client endpoint as a
# fixture consumer. The content host builds through the PRODUCTION pipeline
# (recipe as SYSTEM, activity verified, capture), an unchanged rebuild is a
# cached no-op, and a consumer boots the captured disk with the recipe's
# state intact. Usage: ./run.sh [down]. CID bands 4220/4225.
set -euo pipefail
cd "$(dirname "$0")"
SPIKE="$PWD"
ROOT="$(cd ../../.. && pwd)"
RANGE="$SPIKE/range"

WIN_ISO="${WIN_ISO:-$HOME/.cache/inspect-ranges/images/Win11.iso}"
VIRTIO_ISO="${VIRTIO_ISO:-$HOME/.cache/inspect-ranges/images/virtio-win.iso}"
NOBLE="${NOBLE:-$HOME/.cache/inspect-ranges/images/noble-server-cloudimg-amd64.img}"
export XDG_STATE_HOME="$SPIKE/tmp/state"
# the published range image predates swtpm pins on some fleets; the battery
# builds and uses the local image
unset INSPECT_RANGES_RANGE_IMAGE
IR="uv run inspect-ranges"
IRBIN="$ROOT/.venv/bin/inspect-ranges"
CACHE="$SPIKE/tmp/cache"
BUILDS="$SPIKE/tmp/builds"
FLAGS=(--image-cache "$CACHE" --build-cache "$BUILDS" --cid-base 4220 --readiness-timeout 900)

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

echo "=== C1 goldens into the battery cache ==="
DB_OUT=$($IR daemon-bundle -o "$SPIKE/tmp/artifacts")
DAEMON_SHA=$(echo "$DB_OUT" | { grep -o 'bundle sha256:[0-9a-f]*' || true; } | cut -d: -f2)
[ -n "$DAEMON_SHA" ] || { echo "FAIL  daemon-bundle output carried no sha"; exit 1; }
if $IR images derive-windows "$WIN_ISO" --sha256 "$(sha256sum "$WIN_ISO" | cut -d' ' -f1)" \
    --virtio-iso "$VIRTIO_ISO" --virtio-sha256 "$(sha256sum "$VIRTIO_ISO" | cut -d' ' -f1)" --os 11 \
    --image-cache "$CACHE" --daemon-bundle "$SPIKE/tmp/artifacts" \
    --daemon-sha256 "$DAEMON_SHA" >"$SPIKE/tmp/c1.txt" 2>&1; then
  ok "C1 the windows-11 golden installed into the clean cache"
else
  bad "C1 derive-windows --os 11"; tail -5 "$SPIKE/tmp/c1.txt"; exit 1
fi
$IR images derive "$NOBLE" --sha256 "$(sha256sum "$NOBLE" | cut -d' ' -f1)" --name ubuntu-noble \
  --image-cache "$CACHE" --daemon-bundle "$SPIKE/tmp/artifacts" --daemon-sha256 "$DAEMON_SHA" >/dev/null

echo "=== C2 the client endpoint builds: recipe, verify, capture ==="
if (cd "$RANGE" && "$IRBIN" build "${FLAGS[@]}" --recipe-budget 1800 >"$SPIKE/tmp/c2.txt" 2>&1); then
  grep -q "build OK" "$SPIKE/tmp/c2.txt" && ok "C2 win11-consumer builds green" \
    || { bad "C2 output"; tail -15 "$SPIKE/tmp/c2.txt"; }
else
  bad "C2 build"; tail -25 "$SPIKE/tmp/c2.txt"; exit 1
fi
grep -q "recipe=w11.endpoint" "$SPIKE/tmp/c2.txt" \
  && ok "C2b the endpoint recipe realized (SYSTEM over the daemon)" \
  || bad "C2b recipe line missing"
VOK=$(grep -cE '^verify +ok +activity' "$SPIKE/tmp/c2.txt" || true)
[[ "$VOK" -ge 1 ]] && ok "C2c the activity declaration verified ($VOK ok)" \
  || bad "C2c verify (got: $VOK)"
REALIZED=$(ls "$CACHE" | { grep -c '^win11-consumer-.*\.realized\.json$' || true; })
[[ "$REALIZED" -eq 1 ]] && ok "C2d the provisioned client captured as a realized image" \
  || bad "C2d capture (got: $REALIZED)"

echo "=== C3 an unchanged rebuild is a cached no-op ==="
(cd "$RANGE" && "$IRBIN" build "${FLAGS[@]}" >"$SPIKE/tmp/c3.txt" 2>&1) \
  && grep -q "build OK (cached" "$SPIKE/tmp/c3.txt" \
  && ok "C3 the unchanged range is a cached no-op" \
  || { bad "C3 cached rebuild"; tail -5 "$SPIKE/tmp/c3.txt"; }

echo "=== C4 a consumer boots the captured client ==="
export INSPECT_RANGES_BUILD_CACHE="$BUILDS"
$IR render "$RANGE" -o "$SPIKE/tmp/consumer" --image-cache "$CACHE" --cid-base 4225 >"$SPIKE/tmp/c4-render.txt" 2>&1 \
  && ok "C4 render consumed the manifest" \
  || { bad "C4 render"; tail -8 "$SPIKE/tmp/c4-render.txt"; exit 1; }
if $IR up "$SPIKE/tmp/consumer" --image-cache "$CACHE" --readiness-timeout 900 >"$SPIKE/tmp/c4.txt" 2>&1; then
  ok "C4b up: the captured client booted to daemon readiness"
else
  bad "C4b up"; tail -8 "$SPIKE/tmp/c4.txt"; exit 1
fi
BOOT="$SPIKE/tmp/consumer/boot.json"
PROJECT=$(docker ps --format '{{.Names}}' | { grep -E '^ir-win11-consumer-' || true; } | head -1 | sed 's/-range-1$//')
[ -n "$PROJECT" ] || { bad "C4 no running range container"; echo "$PASS passed, $FAIL failed"; exit 1; }
CHEXEC="uv run python design/spikes/_shared/chexec.py --boot $BOOT --project $PROJECT --guest client --shell cmd exec"
# the first exec can race the clone's post-specialize settling (slice-1 lesson)
MARKER=""
for attempt in 1 2 3 4; do
  MARKER=$($CHEXEC 'cmd /c type C:\ProgramData\endpoint\ready.txt' 2>&1 | tail -1 | tr -d ' \r') && break || sleep 15
done
[[ "$MARKER" == "w11-endpoint-realized" ]] \
  && ok "C4c the recipe's marker rode the captured disk ($MARKER)" \
  || bad "C4c marker (got: $MARKER)"
# capture-then-grep: chexec propagates the guest command's rc, so a missing
# account/task would otherwise abort the battery under pipefail instead of
# recording the FAIL these checks exist for (slice-2 review)
ACCOUNT_OUT=$($CHEXEC 'net user user' 2>&1 || true)
[[ "$(printf '%s' "$ACCOUNT_OUT" | grep -c "User name")" -ge 1 ]] \
  && ok "C4d the low-privilege operator account exists on the booted disk" \
  || bad "C4d account"
TASK_OUT=$($CHEXEC 'schtasks /query /tn Reboot' 2>&1 || true)
[[ "$(printf '%s' "$TASK_OUT" | grep -c "Reboot")" -ge 1 ]] \
  && ok "C4e the SYSTEM maintenance task is registered" \
  || bad "C4e task"

$IR down --all >/dev/null 2>&1 || true
docker ps --format '{{.Names}}' | grep -q '^ir-win11-consumer-' && bad "C5 teardown left containers" || ok "C5 teardown clean"
echo
echo "$PASS passed, $FAIL failed"
exit $((FAIL > 0))
