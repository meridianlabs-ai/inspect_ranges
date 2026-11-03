# Routine endpoint housekeeping: a timestamped heartbeat in the admin log.
$log = 'C:\ProgramData\endpoint\admin.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Add-Content -Path $log -Value ("heartbeat {0}" -f (Get-Date -Format o))
