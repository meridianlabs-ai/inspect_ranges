#!/bin/bash
# vsockd-win spike: port the vsock exec/file daemon to Windows and validate it
# hard. Phases: bootstrap (install daemon, smoke over vsock), conformance
# (self_check + native supplement), batteries (soak, tree-kill via supplement,
# save/restore, reboot, perf). See README.md.
# Usage: ./run.sh [bootstrap|conformance|batteries|all|down]   (default: all)
set -euo pipefail
cd "$(dirname "$0")"

export IMAGE_CACHE="${IMAGE_CACHE:-$HOME/.cache/inspect-ranges/images}"
V="virsh -c qemu:///system"
CID=9
C="python3 harness/v2client.py"
PY="../../../.venv/bin/python"
PHASE="${1:-all}"

if [[ "$PHASE" == "down" ]]; then
  docker compose down -v
  exit 0
fi

for iso in ws2022-eval.iso virtio-win.iso; do
  [[ -f "$IMAGE_CACHE/$iso" ]] || { echo "missing $IMAGE_CACHE/$iso (see win-guest README for sources)"; exit 1; }
done
if [[ ! -f "$IMAGE_CACHE/busybox.exe" ]]; then
  echo "fetching busybox-w32 (GPLv2; test image only) ..."
  curl -fsSL -o "$IMAGE_CACHE/busybox.exe" https://frippery.org/files/busybox/busybox.exe
fi

docker compose up -d --build --wait

if ! docker compose exec -T range test -f /scratch/win-golden.qcow2; then
  echo "=== golden image install (one-time, ~3 min) ==="
  docker compose exec -T range bash /assets/install.sh
  until [[ "$(docker compose exec -T range $V domstate wininstall)" != "running" ]]; do sleep 15; done
  docker compose exec -T range $V undefine wininstall
fi

echo "=== boot guest (vsock CID $CID + virtio-win + payload ISOs) ==="
docker compose exec -T range env CID=$CID bash /assets/boot-vm.sh >/dev/null 2>&1
python3 ga.py wait winvsd 300

echo "=== install: driver + csc compile + service (over qemu-ga, the bootstrap channel) ==="
python3 ga.py ps winvsd 600 < assets/guest/install-daemon.ps1

echo "=== reboot (service autostart + machine PATH pickup), wait on VSOCK ping ==="
BT=$(python3 ga.py boottime winvsd)
python3 ga.py ps winvsd 60 <<'EOF'
& shutdown.exe /r /t 3
EOF
T0=$(date +%s.%N)
python3 ga.py wait-newboot winvsd "$BT" 300
$C wait $CID
T1=$(date +%s.%N)
python3 -c "print(f'reboot -> vsock daemon answering: {$T1-$T0:.1f}s (includes shutdown)')"

echo "=== smoke over vsock: exec + file round trip ==="
$C exec $CID whoami
head -c 1048576 /dev/urandom > tmp/smoke.bin
$C put $CID tmp/smoke.bin 'C:\vsockd\work\smoke.bin'
$C get $CID 'C:\vsockd\work\smoke.bin' tmp/smoke-back.bin
cmp tmp/smoke.bin tmp/smoke-back.bin && echo "PASS 1MB file round trip (bytes identical)"

[[ "$PHASE" == "bootstrap" ]] && { echo "bootstrap OK"; exit 0; }

echo "=== conformance: inspect_ai self_check (busybox-assisted) ==="
"$PY" harness/run_self_check_win.py $CID

echo "=== conformance: Windows-native supplement (incl. tree-kill, background survival) ==="
"$PY" harness/windows_checks.py $CID

[[ "$PHASE" == "conformance" ]] && { echo "conformance OK"; exit 0; }

echo "=== soak: 500 sequential + 50 parallel execs + file round trips ==="
"$PY" harness/soak.py $CID

echo "=== save/restore mid-session (in-flight call severed, next op clean) ==="
$C exec $CID cmd.exe /c "ping -n 10 127.0.0.1 > NUL" &
BGPID=$!
sleep 1
docker compose exec -T range $V save winvsd /scratch/winvsd.sav >/dev/null
wait $BGPID && echo "UNEXPECTED: in-flight call survived save" || echo "in-flight call severed by save (expected; per-op connect recovers)"
docker compose exec -T range $V restore /scratch/winvsd.sav >/dev/null
python3 ga.py settime winvsd
$C wait $CID
$C exec $CID whoami
$C put $CID tmp/smoke.bin 'C:\vsockd\work\smoke2.bin'
echo "PASS exec + file ops after restore"

echo "=== reboot persistence ==="
BT=$(python3 ga.py boottime winvsd)
python3 ga.py ps winvsd 60 <<'EOF'
& shutdown.exe /r /t 3
EOF
python3 ga.py wait-newboot winvsd "$BT" 300
$C wait $CID
$C exec $CID whoami
echo "PASS daemon auto-restarts after reboot"

echo "=== performance ==="
"$PY" harness/perf.py $CID full

echo "OK. Tear down with: ./run.sh down"
