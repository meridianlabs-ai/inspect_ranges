#!/bin/bash
# Checkpoint-clone spike: build a converged AD pair ON A NAMED CPU MODEL,
# capture a bundled checkpoint (disks + memory + domain XML), restart the
# range container to drop all libvirt state, then run two independent samples
# from the bundle: a destructive one, then a second that must come up
# pristine. See README.md. Usage: ./run.sh [down]
set -euo pipefail
cd "$(dirname "$0")"

export IMAGE_CACHE="${IMAGE_CACHE:-$HOME/.cache/inspect-ranges/images}"
V="virsh -c qemu:///system"

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

sid_of() {
  python3 ga.py ps "$1" 180 2>/dev/null <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$sid = (Get-CimInstance Win32_UserAccount -Filter "LocalAccount='True' AND Name='Administrator'").SID
$sid -replace '-500$', ''
EOF
}

configure_guest() {  # $1 domain, $2 ip, $3 dns, $4 newname
  python3 ga.py ps "$1" 300 <<EOF
\$ProgressPreference = 'SilentlyContinue'
\$ErrorActionPreference = 'Stop'
\$a = Get-NetAdapter | Sort-Object ifIndex | Select-Object -First 1
Set-NetIPInterface -InterfaceIndex \$a.ifIndex -Dhcp Disabled
New-NetIPAddress -InterfaceIndex \$a.ifIndex -IPAddress $2 -PrefixLength 24 | Out-Null
Set-DnsClientServerAddress -InterfaceIndex \$a.ifIndex -ServerAddresses $3
Rename-Computer -NewName $4 -Force -WarningAction SilentlyContinue | Out-Null
& shutdown.exe /r /t 3
EOF
}

echo "=== build: boot clones on named CPU model, promote, sysprep, join ==="
TBUILD=$(date +%s)
docker compose exec -T range bash /assets/boot-ad.sh >/dev/null 2>&1
python3 ga.py wait dc01 300
python3 ga.py wait ws01 300
docker compose exec -T range sh -c "$V dumpxml dc01 | grep -A2 '<cpu'" | head -3

SID_GOLD=$(sid_of ws01)

echo "--- sysprep ws01 now (runs while the DC is promoted) ---"
python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
$xml = @'
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <ComputerName>*</ComputerName>
      <TimeZone>UTC</TimeZone>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-International-Core" processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideLocalAccountScreen>true</HideLocalAccountScreen>
        <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
      <UserAccounts>
        <AdministratorPassword>
          <Value>Sp1keAdm!n2026</Value><PlainText>true</PlainText>
        </AdministratorPassword>
      </UserAccounts>
    </component>
  </settings>
</unattend>
'@
Set-Content -Path C:\sysprep-unattend.xml -Value $xml -Encoding UTF8
Start-Process -FilePath C:\Windows\System32\Sysprep\sysprep.exe `
  -ArgumentList '/generalize', '/oobe', '/reboot', '/quiet', '/unattend:C:\sysprep-unattend.xml'
EOF

echo "--- configure + promote dc01 meanwhile ---"
BT_DC=$(python3 ga.py boottime dc01)
configure_guest dc01 10.10.10.5 127.0.0.1 DC01
python3 ga.py wait-newboot dc01 "$BT_DC" 600
BT_DC=$(python3 ga.py boottime dc01)
python3 ga.py ps dc01 1200 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools | Out-Null
$pw = ConvertTo-SecureString 'Sp1keAdm!n2026' -AsPlainText -Force
Install-ADDSForest -DomainName range.lab -DomainNetbiosName RANGE `
  -SafeModeAdministratorPassword $pw -InstallDns -Force -NoRebootOnCompletion `
  -WarningAction SilentlyContinue | Out-Null
& shutdown.exe /r /t 3
EOF
python3 ga.py wait-newboot dc01 "$BT_DC" 900
converged=""
for _ in $(seq 1 90); do
  if python3 ga.py ps dc01 60 >/dev/null 2>&1 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
Get-ADDomain range.lab | Out-Null
Resolve-DnsName -Type SRV _ldap._tcp.range.lab -Server 127.0.0.1 | Out-Null
EOF
  then converged=1; break; fi
  sleep 10
done
[[ -n "$converged" ]] || { echo "DC never converged"; exit 1; }

echo "--- wait for ws01 sysprep (new SID), reconfigure, join ---"
newsid=""
for _ in $(seq 1 180); do
  s=$(sid_of ws01 || true)
  if [[ -n "$s" && "$s" != "$SID_GOLD" ]]; then newsid="$s"; break; fi
  sleep 5
done
[[ -n "$newsid" ]] || { echo "ws01 never specialized"; exit 1; }
BT_WS=$(python3 ga.py boottime ws01)
configure_guest ws01 10.10.10.20 10.10.10.5 WS01
python3 ga.py wait-newboot ws01 "$BT_WS" 600
BT_WS=$(python3 ga.py boottime ws01)
python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Resolve-DnsName dc01.range.lab | Out-Null
$pw = ConvertTo-SecureString 'Sp1keAdm!n2026' -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential('RANGE\Administrator', $pw)
Add-Computer -DomainName range.lab -Credential $cred -Force -WarningAction SilentlyContinue
& shutdown.exe /r /t 3
EOF
python3 ga.py wait-newboot ws01 "$BT_WS" 600

python3 ga.py ps dc01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
New-ADUser tester -AccountPassword (ConvertTo-SecureString 'T3ster!2026' -AsPlainText -Force) -Enabled $true
(Get-ADComputer WS01).DNSHostName
EOF
python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
if (-not (Test-ComputerSecureChannel)) { exit 1 }
'converged domain verified'
EOF
echo "build (boot -> converged, verified): $(( $(date +%s) - TBUILD ))s"

echo "=== checkpoint: save pair, bundle disks + memory + XML, drop libvirt state ==="
TCKPT=$(date +%s)
docker compose exec -T range sh -c "mkdir -p /scratch/ckpt && $V dumpxml dc01 > /scratch/ckpt/dc01.xml && $V dumpxml ws01 > /scratch/ckpt/ws01.xml"
docker compose exec -T range $V save dc01 /scratch/ckpt/dc01.mem >/dev/null
docker compose exec -T range $V save ws01 /scratch/ckpt/ws01.mem >/dev/null
docker compose exec -T range sh -c "mv /scratch/dc01.qcow2 /scratch/ckpt/ && mv /scratch/ws01.qcow2 /scratch/ckpt/ && $V undefine dc01 && $V undefine ws01 && ls -lh /scratch/ckpt/"
echo "checkpoint capture: $(( $(date +%s) - TCKPT ))s"
echo "--- recreate the container: the bundle must not depend on libvirt state ---"
docker compose up -d --force-recreate --wait

instantiate() {  # fresh overlays on the bundle, restore, fix clocks
  docker compose exec -T range sh -c '
    set -e
    ip link add br-ad type bridge 2>/dev/null || true
    ip link set br-ad up
    qemu-img create -f qcow2 -F qcow2 -b /scratch/ckpt/dc01.qcow2 /scratch/dc01.qcow2 40G >/dev/null
    qemu-img create -f qcow2 -F qcow2 -b /scratch/ckpt/ws01.qcow2 /scratch/ws01.qcow2 40G >/dev/null
  '
  docker compose exec -T range $V restore /scratch/ckpt/dc01.mem >/dev/null
  docker compose exec -T range $V restore /scratch/ckpt/ws01.mem >/dev/null
  python3 ga.py wait dc01 120
  python3 ga.py wait ws01 120
  python3 ga.py settime dc01
  python3 ga.py settime ws01
}

discard() {
  docker compose exec -T range sh -c "$V destroy dc01; $V destroy ws01; rm -f /scratch/dc01.qcow2 /scratch/ws01.qcow2"
}

echo "=== sample A: instantiate, plant secret, verify, then be destructive ==="
TA=$(date +%s)
instantiate
echo "sample A instantiate (overlays + restore pair + clocks): $(( $(date +%s) - TA ))s"
SECRET_A="FLAG{$(openssl rand -hex 8)}"
python3 ga.py ps dc01 300 <<EOF
\$ProgressPreference = 'SilentlyContinue'
\$ErrorActionPreference = 'Stop'
Set-Content -Path C:\\sample-secret.txt -Value '$SECRET_A'
Import-Module ActiveDirectory
Get-ADDomain range.lab | Out-Null
'A: domain healthy, secret planted'
EOF
python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
if (-not (Test-ComputerSecureChannel)) { exit 1 }
'A: secure channel OK'
EOF
python3 ga.py ps dc01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
Remove-ADUser tester -Confirm:$false
'A: destroyed - removed RANGE\tester'
EOF
python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Set-Content -Path C:\junk.txt -Value 'residue from sample A'
'A: destroyed - junk file on member'
EOF
discard >/dev/null

echo "=== sample B: fresh instantiation must show no trace of sample A ==="
TB=$(date +%s)
instantiate
echo "sample B instantiate: $(( $(date +%s) - TB ))s"
SECRET_B="FLAG{$(openssl rand -hex 8)}"
python3 ga.py ps dc01 300 <<EOF
\$ProgressPreference = 'SilentlyContinue'
\$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
Get-ADDomain range.lab | Out-Null
if (-not (Get-ADUser -Filter "SamAccountName -eq 'tester'")) { 'B: FAIL tester missing'; exit 1 }
'B: tester present (sample A deletion did not persist)'
if (Test-Path C:\\sample-secret.txt) { 'B: FAIL sample A secret persisted'; exit 1 }
'B: sample A secret absent'
Set-Content -Path C:\\sample-secret.txt -Value '$SECRET_B'
if ((Get-Content C:\\sample-secret.txt) -ne '$SECRET_B') { exit 1 }
'B: fresh secret planted and read back'
EOF
python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
if (Test-Path C:\junk.txt) { 'B: FAIL junk from sample A persisted'; exit 1 }
'B: no junk from sample A'
if (-not (Test-ComputerSecureChannel)) { exit 1 }
'B: secure channel OK'
EOF
discard >/dev/null

echo "TOTAL build: $(( TCKPT - TBUILD ))s | per-sample instantiation measured above"
echo "OK. Tear down with: ./run.sh down"
