#!/bin/bash
# viosock spike: prove the stock virtio-win ISO's WHQL-signed Windows vsock
# driver installs, binds, and carries stream traffic between a Linux host and
# a native Windows Winsock listener. See README.md. Usage: ./run.sh [down]
set -euo pipefail
cd "$(dirname "$0")"

export IMAGE_CACHE="${IMAGE_CACHE:-$HOME/.cache/inspect-ranges/images}"
V="virsh -c qemu:///system"
CID=9

if [[ "${1:-}" == "down" ]]; then
  docker compose down -v
  exit 0
fi

for iso in ws2022-eval.iso virtio-win.iso; do
  [[ -f "$IMAGE_CACHE/$iso" ]] || { echo "missing $IMAGE_CACHE/$iso (see win-guest README for sources)"; exit 1; }
done

docker compose up -d --build --wait

if ! docker compose exec -T range test -f /scratch/win-golden.qcow2; then
  echo "=== golden image install (one-time, ~3 min) ==="
  docker compose exec -T range bash /assets/install.sh
  until [[ "$(docker compose exec -T range $V domstate wininstall)" != "running" ]]; do sleep 15; done
  docker compose exec -T range $V undefine wininstall
fi

echo "=== driver provenance: viosock on the stable ISO, signature ==="
docker compose exec -T range sh -c 'command -v 7z >/dev/null || (apt-get update -qq && apt-get install -y -qq p7zip-full) >/dev/null 2>&1; 7z l /images/virtio-win.iso | grep "viosock/2k22/amd64" | grep -v pdb'

echo "=== boot guest with vsock device + virtio-win ISO ==="
docker compose exec -T range sh -c "
set -e
$V destroy vsocktest 2>/dev/null || true
$V undefine vsocktest 2>/dev/null || true
rm -f /scratch/vsocktest.qcow2
qemu-img create -f qcow2 -F qcow2 -b /scratch/win-golden.qcow2 /scratch/vsocktest.qcow2 40G >/dev/null
virt-install --connect qemu:///system --name vsocktest --memory 4096 --vcpus 4 \
  --cpu host-passthrough \
  --disk path=/scratch/vsocktest.qcow2,format=qcow2,bus=virtio \
  --disk path=/images/virtio-win.iso,device=cdrom,readonly=on \
  --network none --vsock cid.address=$CID \
  --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
  --boot hd --graphics vnc,listen=127.0.0.1 --osinfo win2k22 --import --noautoconsole >/dev/null
"
python3 ga.py wait vsocktest 300

echo "=== install driver (pnputil, no test-signing), check binding ==="
python3 ga.py ps vsocktest 300 <<'EOF' 2>/dev/null
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
'device before:'
(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'DEV_1053' } | Select-Object -First 1 | ForEach-Object { "$($_.Status)  $($_.FriendlyName)" })
$cd = (Get-Volume | Where-Object DriveType -eq 'CD-ROM' | Select-Object -First 1).DriveLetter
# pnputil may exit 3010 (success, reboot advised), which PowerShell would
# propagate; judge success by the device actually binding instead
& pnputil.exe /add-driver "${cd}:\viosock\2k22\amd64\viosock.inf" /install | Out-Null
Start-Sleep -Seconds 3
$dev = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'DEV_1053' } | Select-Object -First 1
"device after: $($dev.Status)  $($dev.FriendlyName)"
$catalog = cmd /c "netsh winsock show catalog" | Select-String 'Virtio Vsock' | Select-Object -First 1
"winsock catalog: $catalog"
if ($dev.Status -ne 'OK') { exit 1 }
exit 0
EOF

echo "=== native Winsock listener in guest, connect from Linux host over vsock ==="
python3 ga.py ps vsocktest 180 >/dev/null 2>&1 <<PSEOF
\$ProgressPreference = 'SilentlyContinue'
\$listener = @'
$(cat assets/listener.ps1)
'@
Set-Content -Path C:\\listener.ps1 -Value \$listener
Remove-Item C:\\vsock-listen.txt, C:\\vsock-result.txt, C:\\vsock-error.txt -ErrorAction SilentlyContinue
Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\\listener.ps1'
PSEOF
sleep 10
python3 ga.py ps vsocktest 60 2>/dev/null <<'EOF'
if (Test-Path C:\vsock-error.txt) { Get-Content C:\vsock-error.txt | Select-Object -First 3; exit 1 }
if (-not (Test-Path C:\vsock-listen.txt)) { 'listener not up'; exit 1 }
'guest listening on vsock port 5000'
EOF
python3 - "$CID" <<'EOF'
import socket, sys
s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
s.settimeout(10)
s.connect((int(sys.argv[1]), 5000))
s.sendall(b"hello-from-host")
print("host received:", s.recv(64).decode())
s.close()
EOF
python3 ga.py ps vsocktest 60 2>/dev/null <<'EOF'
'guest recorded: ' + (Get-Content C:\vsock-result.txt)
EOF

echo "OK. Tear down with: ./run.sh down"
