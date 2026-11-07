# In-guest setup for vsockd v3 on Windows. Runs as SYSTEM over the bootstrap
# channel (qemu-ga at build time). Finds the payload CD (the one carrying
# Wire.cs), installs the viosock driver from the virtio-win CD, compiles the
# daemon with the in-box .NET Framework 4.8 csc.exe (every source is C# 5),
# and registers it as an auto-start service with restart-on-failure.
# Test-image staging (busybox, C:\tmp, /etc fixtures, rangeuser) happens only
# when the payload carries busybox.exe; production goldens get none of it.
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

# the virtio-win CD signs drivers per OS: client installs (ProductType 1,
# e.g. Windows 11) take w11, servers take 2k22
$winDir = if ((Get-CimInstance Win32_OperatingSystem).ProductType -eq 1) { 'w11' } else { '2k22' }
$cds = Get-Volume | Where-Object DriveType -eq 'CD-ROM' | ForEach-Object { $_.DriveLetter }
$payload = $cds | Where-Object { Test-Path "${_}:\Wire.cs" } | Select-Object -First 1
$virtio  = $cds | Where-Object { Test-Path "${_}:\viosock\$winDir\amd64\viosock.inf" } | Select-Object -First 1
if (-not $payload) { throw 'payload CD not found' }
if (-not $virtio)  { throw 'virtio-win CD not found' }

# viosock driver (WHQL-signed; judge success by device binding, since pnputil
# may exit 3010 for success-reboot-advised)
& pnputil.exe /add-driver "${virtio}:\viosock\$winDir\amd64\viosock.inf" /install | Out-Null
Start-Sleep -Seconds 3
$dev = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'DEV_1053' } | Select-Object -First 1
if ($dev.Status -ne 'OK') { throw "viosock device not OK: $($dev.Status)" }

New-Item -ItemType Directory -Force -Path C:\guestd, C:\guestd\work | Out-Null

# C:\ grants Authenticated Users Modify by inheritance, which would leave the
# SYSTEM service binary user-replaceable: a harness-made local privesc on the
# exact machines whose task is local privesc (verified live, 2026-11-07).
# Strip inheritance before anything lands. SYSTEM (S-1-5-18) and
# Administrators (S-1-5-32-544) own the tree; Authenticated Users (S-1-5-11)
# keep list-and-traverse on the directory itself plus Modify strictly inside
# work, because user= execs under profile-less accounts use work as their
# home. SIDs, not names: goldens install on non-English Windows too.
& icacls.exe C:\guestd /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-11:(RX)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls C:\guestd failed: $LASTEXITCODE" }
# work's ACL is fully explicit too: it predates the parent lockdown, and NTFS
# propagation of inherited-ACE removal is not a thing to lean on
& icacls.exe C:\guestd\work /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-11:(OI)(CI)(M)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls C:\guestd\work failed: $LASTEXITCODE" }

foreach ($src in 'Wire.cs', 'Store.cs', 'Exec.cs', 'Daemon.cs', 'Program.cs') {
    Copy-Item "${payload}:\$src" C:\guestd\
}

# compile with the in-box .NET Framework 4.8 compiler (C# 5)
$csc = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /optimize /target:exe /out:C:\guestd\guestd.exe `
  /r:System.ServiceProcess.dll `
  C:\guestd\Wire.cs C:\guestd\Store.cs C:\guestd\Exec.cs C:\guestd\Daemon.cs C:\guestd\Program.cs
if ($LASTEXITCODE -ne 0) { throw "csc failed: $LASTEXITCODE" }

# the sources are compile-time material: the repo ships them, the guest keeps
# only the binary (recipes-not-images), and a readable protocol listing on a
# target is recon material the daemon does not need to hand out
Remove-Item -Force C:\guestd\*.cs

if (Test-Path "${payload}:\busybox.exe") {
    # test-image-only pieces: local user for user= exec, busybox applets in
    # C:\usr\bin (also the suite's /usr/bin cwd fixture), C:\tmp, /etc/passwd
    $pw = 'R4nge!User2026'
    if (-not (Get-LocalUser -Name rangeuser -ErrorAction SilentlyContinue)) {
        net user rangeuser $pw /add /y | Out-Null
    }
    Set-Content -Path C:\guestd\users.txt -Value "rangeuser:$pw"
    New-Item -ItemType Directory -Force -Path C:\usr\bin, C:\tmp, C:\etc | Out-Null
    Set-Content -Path C:\etc\passwd -Value 'root:x:0:0:root:/root:/bin/sh'
    Copy-Item "${payload}:\busybox.exe" C:\usr\bin\
    & C:\usr\bin\busybox.exe --install C:\usr\bin | Out-Null
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if ($machinePath -notmatch 'usr\\bin') {
        [Environment]::SetEnvironmentVariable('Path', "$machinePath;C:\usr\bin", 'Machine')
    }
}

# service: auto start, restart on failure (the daemon additionally supervises
# its own listener, so a wedged accept loop recovers without any restart)
if (Get-Service guestd -ErrorAction SilentlyContinue) {
    sc.exe stop guestd | Out-Null
    sc.exe delete guestd | Out-Null
    Start-Sleep -Seconds 2
}
sc.exe create guestd binPath= 'C:\guestd\guestd.exe' start= auto | Out-Null
sc.exe failure guestd reset= 86400 actions= restart/5000/restart/5000/restart/5000 | Out-Null
sc.exe start guestd | Out-Null

'install-daemon: OK'
exit 0
