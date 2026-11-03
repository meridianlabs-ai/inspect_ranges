$ErrorActionPreference = 'Stop'

# -- the declared low-privilege operator (users:) ------------------------------
if (-not (Get-LocalUser -Name 'user' -ErrorAction SilentlyContinue)) {
    net user user 'users@drool' /add /y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "net user add failed: $LASTEXITCODE" }
}
Add-LocalGroupMember -Group 'Users' -Member 'user' -ErrorAction SilentlyContinue
Set-LocalUser -Name 'user' -PasswordNeverExpires $true

# -- an on-demand SYSTEM reboot task (client scenarios bounce the machine,
# -- and so their services, through it; the captured disk carries it) ----------
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c shutdown /r /t 5'
Register-ScheduledTask -TaskName 'Reboot' -Action $action `
    -User 'SYSTEM' -RunLevel Highest -Force | Out-Null

# -- the endpoint marker the battery reads back off the captured disk ----------
New-Item -ItemType Directory -Force -Path 'C:\ProgramData\endpoint' | Out-Null
Set-Content -Path 'C:\ProgramData\endpoint\ready.txt' -Value 'w11-endpoint-realized'

'w11.endpoint: ok'
