#!/bin/bash
# Dev-loop helper: push the current VsockDaemon.cs into the running guest
# (over qemu-ga, base64 via the encoded-command channel is too small, so use
# the daemon's own write op when it works, else ga chunks), recompile with the
# in-box csc, restart the service. Usage: ./redeploy.sh
set -euo pipefail
cd "$(dirname "$0")"

# push source via the daemon's own write op; fall back to chunked base64 over
# qemu-ga when the running daemon build is too broken to carry it
if ! python3 harness/v2client.py put 9 assets/guest/VsockDaemon.cs 'C:\vsockd\VsockDaemon.new.cs'; then
  echo "daemon put failed; pushing over qemu-ga in chunks"
  python3 ga.py ps winvsd 60 <<'EOF'
Remove-Item C:\vsockd\stage.b64 -ErrorAction SilentlyContinue
exit 0
EOF
  base64 -w0 assets/guest/VsockDaemon.cs > tmp/stage.b64
  split -b 12000 tmp/stage.b64 tmp/stage.part.
  for part in tmp/stage.part.*; do
    python3 ga.py ps winvsd 60 <<EOF
Add-Content -Path C:\\vsockd\\stage.b64 -Value '$(cat "$part")' -NoNewline
exit 0
EOF
  done
  rm -f tmp/stage.b64 tmp/stage.part.*
  python3 ga.py ps winvsd 60 <<'EOF'
$b64 = Get-Content C:\vsockd\stage.b64 -Raw
[IO.File]::WriteAllBytes('C:\vsockd\VsockDaemon.new.cs', [Convert]::FromBase64String($b64))
Remove-Item C:\vsockd\stage.b64
'staged via ga'
exit 0
EOF
fi

python3 ga.py ps winvsd 300 <<'EOF'
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
sc.exe stop vsockd | Out-Null
Start-Sleep -Seconds 2
attrib -r C:\vsockd\VsockDaemon.cs 2>$null
Move-Item -Force C:\vsockd\VsockDaemon.new.cs C:\vsockd\VsockDaemon.cs
$csc = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /optimize /target:exe /out:C:\vsockd\vsockd.exe `
  /r:System.Web.Extensions.dll /r:System.ServiceProcess.dll `
  C:\vsockd\VsockDaemon.cs
if ($LASTEXITCODE -ne 0) { throw "csc failed: $LASTEXITCODE" }
sc.exe start vsockd | Out-Null
'redeployed'
EOF
python3 harness/v2client.py wait 9 60
