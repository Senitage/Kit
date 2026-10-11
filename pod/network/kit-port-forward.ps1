# Keeps Kit's port (8600) reachable from the home network, so the Pod can reach
# Kit's server inside WSL. WSL's internal address can change when the PC restarts;
# this points the Windows port forward at whatever it is now.
#
# Set up once, in an admin PowerShell, from the folder this file is in:
#   .\kit-port-forward.ps1 -Install
# That registers a task that runs this at every logon (with admin rights, as netsh
# needs them). Run it by hand any time with: .\kit-port-forward.ps1

param([switch]$Install, [string]$Distro = "Ubuntu-24.04", [int]$Port = 8600)

if ($Install) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" -Distro $Distro -Port $Port"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $trigger.Delay = "PT30S"  # give WSL and Kit a moment to start
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive
    Register-ScheduledTask -TaskName "Kit port forward" -Action $action -Trigger $trigger `
        -Principal $principal -Force | Out-Null
    Write-Host "Installed: 'Kit port forward' runs at every logon."
}

# WSL's address now (starting the distro if it isn't running yet).
# (Skips Tailscale's 100.x address, which the home network can't use.)
$ip = (wsl.exe -d $Distro -- hostname -I).Trim().Split(" ") | Where-Object { $_ -and $_ -notlike "100.*" -and $_ -notlike "*:*" } | Select-Object -First 1
if (-not $ip) { Write-Host "Couldn't get WSL's address."; exit 1 }

netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port 2>$null | Out-Null
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$Port connectaddress=$ip connectport=$Port
Write-Host "Port $Port now forwards to WSL at $ip."
