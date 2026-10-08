#!/bin/bash
# AD domain spike: promote a Server 2022 DC and join a member, both cloned
# from the same golden image, driven entirely over qemu-ga through the range
# container. Documents the duplicate-SID join refusal (clones, no sysprep)
# and then the working path (sysprep /generalize the member). See README.md.
# Usage: ./run.sh [down]
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
  T0=$(date +%s)
  docker compose exec -T range bash /assets/install.sh
  until [[ "$(docker compose exec -T range $V domstate wininstall)" != "running" ]]; do sleep 15; done
  echo "golden install: $(( $(date +%s) - T0 ))s"
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

join_domain() {  # $1 domain
  python3 ga.py ps "$1" 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Resolve-DnsName dc01.range.lab | Out-Null
$pw = ConvertTo-SecureString 'Sp1keAdm!n2026' -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential('RANGE\Administrator', $pw)
Add-Computer -DomainName range.lab -Credential $cred -Force -WarningAction SilentlyContinue
& shutdown.exe /r /t 3
EOF
}

echo "=== boot dc01 + ws01 (clones of one golden image, no sysprep) ==="
TSTART=$(date +%s)
docker compose exec -T range bash /assets/boot-ad.sh >/dev/null 2>&1
python3 ga.py wait dc01 300
python3 ga.py wait ws01 300
echo "boot -> both agents up: $(( $(date +%s) - TSTART ))s"

SID_DC=$(sid_of dc01)
SID_WS=$(sid_of ws01)
echo "machine SIDs: dc01=$SID_DC ws01=$SID_WS"
[[ "$SID_DC" == "$SID_WS" ]] && echo "identical, as expected for unsysprepped clones"

BT_DC=$(python3 ga.py boottime dc01)
BT_WS=$(python3 ga.py boottime ws01)
echo "=== configure guests (static IP, DNS, rename, reboot) ==="
configure_guest ws01 10.10.10.20 10.10.10.5 WS01
configure_guest dc01 10.10.10.5 127.0.0.1 DC01
python3 ga.py wait-newboot ws01 "$BT_WS" 600
python3 ga.py wait-newboot dc01 "$BT_DC" 600

echo "=== promote dc01 to forest root (range.lab) ==="
TPROMO=$(date +%s)
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
echo "feature install + forest config: $(( $(date +%s) - TPROMO ))s (reboot pending)"
python3 ga.py wait-newboot dc01 "$BT_DC" 900

echo "=== wait for AD DS convergence (Get-ADDomain + DNS SRV) ==="
TCONV=$(date +%s)
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
echo "promotion total (start -> AD DS answering): $(( $(date +%s) - TPROMO ))s (post-reboot convergence: $(( $(date +%s) - TCONV ))s)"

echo "=== join attempt with duplicate machine SID (expected: refused) ==="
if join_domain ws01 2> tmp/join-dup.err; then
  echo "UNEXPECTED: duplicate-SID join succeeded"; exit 1
fi
grep -q "identical" tmp/join-dup.err \
  && echo "refused: domain SID (from dc01's machine SID) == ws01's machine SID; Windows demands sysprep" \
  || { echo "join failed for an unexpected reason:"; cat tmp/join-dup.err; exit 1; }

echo "=== sysprep /generalize ws01 (the fix), measure specialize cost ==="
TSYS=$(date +%s)
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
# Detached: sysprep runs for minutes and ends in a reboot, which destroys the
# guest-exec session; completion is detected by the SID-change poll below.
Start-Process -FilePath C:\Windows\System32\Sysprep\sysprep.exe `
  -ArgumentList '/generalize', '/oobe', '/reboot', '/quiet', '/unattend:C:\sysprep-unattend.xml'
EOF

newsid=""
for _ in $(seq 1 180); do
  s=$(sid_of ws01 || true)
  if [[ -n "$s" && "$s" != "$SID_WS" ]]; then newsid="$s"; break; fi
  sleep 5
done
[[ -n "$newsid" ]] || { echo "ws01 never came back with a new SID"; exit 1; }
echo "sysprep -> specialized, new SID $newsid: $(( $(date +%s) - TSYS ))s"

echo "=== reconfigure ws01 (sysprep reset the NIC and name) ==="
BT_WS=$(python3 ga.py boottime ws01)
configure_guest ws01 10.10.10.20 10.10.10.5 WS01
python3 ga.py wait-newboot ws01 "$BT_WS" 600

echo "=== join ws01 to range.lab (post-sysprep) ==="
TJOIN=$(date +%s)
BT_WS=$(python3 ga.py boottime ws01)
join_domain ws01
python3 ga.py wait-newboot ws01 "$BT_WS" 600
echo "member join (start -> rebooted into domain): $(( $(date +%s) - TJOIN ))s"

echo "=== verify: secure channel + DC's view + Kerberos auth as a domain user ==="
python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
hostname
if (-not (Test-ComputerSecureChannel)) { exit 1 }
'secure channel: OK'
EOF

python3 ga.py ps dc01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
(Get-ADComputer WS01).DNSHostName
New-ADUser tester -AccountPassword (ConvertTo-SecureString 'T3ster!2026' -AsPlainText -Force) -Enabled $true
'domain user created: RANGE\tester'
EOF

python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
& net.exe use \\dc01.range.lab\SYSVOL /user:RANGE\tester T3ster!2026 | Out-Null
if ($LASTEXITCODE -ne 0) { 'SMB auth as RANGE\tester FAILED'; exit 1 }
'SMB auth as RANGE\tester: OK'
& net.exe use \\dc01.range.lab\SYSVOL /delete | Out-Null
EOF

echo "=== save/restore the converged pair (the boot-storm answer for AD) ==="
TSAVE=$(date +%s)
docker compose exec -T range $V save dc01 /scratch/dc01.sav >/dev/null
docker compose exec -T range $V save ws01 /scratch/ws01.sav >/dev/null
TRESTORE=$(date +%s)
docker compose exec -T range $V restore /scratch/dc01.sav >/dev/null
docker compose exec -T range $V restore /scratch/ws01.sav >/dev/null
python3 ga.py wait dc01 120
python3 ga.py wait ws01 120
python3 ga.py settime dc01
python3 ga.py settime ws01
TBACK=$(date +%s)
echo "save both: $(( TRESTORE - TSAVE ))s | restore both -> agents up + clocks fixed: $(( TBACK - TRESTORE ))s"

python3 ga.py ps ws01 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
if (-not (Test-ComputerSecureChannel)) { exit 1 }
'secure channel after restore: OK'
EOF

echo "TOTAL (boot clones -> verified domain, incl. duplicate-SID detour): $(( TSAVE - TSTART ))s"
echo "OK. Tear down with: ./run.sh down"
