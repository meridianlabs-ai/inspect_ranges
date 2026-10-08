#!/bin/bash
# Windows guest spike: unattended WS2022-eval install under the range
# container, then boot/exec/file/save-restore measurements and the vsock
# driver probe. See README.md. Usage: ./run.sh [down]
set -euo pipefail
cd "$(dirname "$0")"

export IMAGE_CACHE="${IMAGE_CACHE:-$HOME/.cache/inspect-ranges/images}"
GA="docker compose exec range virsh -c qemu:///system qemu-agent-command wintest"

if [[ "${1:-}" == "down" ]]; then
  docker compose down -v
  exit 0
fi

for iso in ws2022-eval.iso virtio-win.iso; do
  [[ -f "$IMAGE_CACHE/$iso" ]] || { echo "missing $IMAGE_CACHE/$iso (see README for sources)"; exit 1; }
done

docker compose up -d --build --wait

if ! docker compose exec range test -f /scratch/win-golden.qcow2; then
  echo "=== unattended install (one-time, ~3 min) ==="
  T0=$(date +%s)
  docker compose exec range bash /assets/install.sh
  until [[ "$(docker compose exec range virsh -c qemu:///system domstate wininstall)" != "running" ]]; do
    sleep 15
  done
  echo "install wall time: $(( $(date +%s) - T0 ))s"
  docker compose exec range virsh -c qemu:///system undefine wininstall
fi

echo "=== boot from golden overlay -> qemu-ga responsive ==="
T0=$(date +%s.%N)
docker compose exec range bash /assets/boot-test.sh >/dev/null 2>&1
until $GA '{"execute":"guest-ping"}' >/dev/null 2>&1; do sleep 0.5; done
T1=$(date +%s.%N)
python3 -c "print(f'boot -> ga: {$T1-$T0:.1f}s')"

echo "=== exec via qemu-ga ==="
PID=$($GA '{"execute":"guest-exec","arguments":{"path":"cmd.exe","arg":["/c","whoami & hostname"],"capture-output":true}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['return']['pid'])")
sleep 2
$GA "{\"execute\":\"guest-exec-status\",\"arguments\":{\"pid\":$PID}}" \
  | python3 -c "import json,sys,base64; r=json.load(sys.stdin)['return']; print(base64.b64decode(r.get('out-data','')).decode(errors='replace').strip())"

echo "=== vsock driver probe (expected: DEV_1053 unbound/Error) ==="
PID=$($GA '{"execute":"guest-exec","arguments":{"path":"powershell.exe","arg":["-Command","Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match \"VEN_1AF4\"} | Select-Object Status,FriendlyName | Format-Table -HideTableHeaders"],"capture-output":true}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['return']['pid'])")
sleep 6
$GA "{\"execute\":\"guest-exec-status\",\"arguments\":{\"pid\":$PID}}" \
  | python3 -c "import json,sys,base64; r=json.load(sys.stdin)['return']; print(base64.b64decode(r.get('out-data','')).decode(errors='replace').strip())"

echo "=== qemu-ga file transfer (5MB each way; 64KB chunks: virsh CLI arg limit) ==="
python3 assets/file-bench.py

echo "=== save / restore (4GB RAM) ==="
T0=$(date +%s.%N)
docker compose exec range virsh -c qemu:///system save wintest /scratch/win.sav >/dev/null
T1=$(date +%s.%N)
docker compose exec range virsh -c qemu:///system restore /scratch/win.sav >/dev/null
T2=$(date +%s.%N)
until $GA '{"execute":"guest-ping"}' >/dev/null 2>&1; do sleep 0.2; done
T3=$(date +%s.%N)
python3 -c "print(f'save: {$T1-$T0:.1f}s | restore: {$T2-$T1:.1f}s | ga after restore: {$T3-$T2:.1f}s')"

echo "OK. Tear down with: ./run.sh down"
