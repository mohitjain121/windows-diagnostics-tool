#requires -RunAsAdministrator
<#
  Reversible fixes for a "sleep -> instant wake" loop (PC won't stay asleep).

  Two independent levers:
    -WakeDevices <names>       Remove wake permission from the given devices
                               (spurious wakes often come from the network
                               adapter or a wireless mouse). Reverse with -Undo.
    -DisableMemoryIntegrity    Turn OFF Memory Integrity / HVCI, the
                               virtualization-based feature that can break S3
                               sleep on some (esp. AMD AM5) systems. This is a
                               security setting - only pass it deliberately.
                               Reverse with -Undo.

  Find wake-armed devices first:  powercfg /devicequery wake_armed

  Examples:
    .\fix-sleep.ps1 -WakeDevices 'Network Adapter','Wireless Mouse'
    .\fix-sleep.ps1 -DisableMemoryIntegrity
    .\fix-sleep.ps1 -WakeDevices 'Network Adapter' -DisableMemoryIntegrity
    .\fix-sleep.ps1 -Undo -DisableMemoryIntegrity          # revert
#>
param(
  [string[]]$WakeDevices = @(),
  [switch]$DisableMemoryIntegrity,
  [switch]$Undo
)

if (-not $WakeDevices) {
  Write-Host "Devices currently allowed to wake this PC:" -ForegroundColor Cyan
  powercfg /devicequery wake_armed
  Write-Host "`nRe-run with -WakeDevices '<name>','<name>' to disable wake for the ones you want." -ForegroundColor Yellow
}

foreach ($dev in $WakeDevices) {
  if ($Undo) {
    powercfg /deviceenablewake "$dev"  2>$null
    Write-Host "  wake ENABLED : $dev" -ForegroundColor Yellow
  } else {
    powercfg /devicedisablewake "$dev" 2>$null
    Write-Host "  wake disabled: $dev" -ForegroundColor Green
  }
}

if ($DisableMemoryIntegrity) {
  $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity'
  if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
  $val = if ($Undo) { 1 } else { 0 }
  Set-ItemProperty -Path $key -Name 'Enabled' -Value $val -Type DWord
  Write-Host "  Memory Integrity (HVCI) Enabled = $val  (reboot required)" -ForegroundColor Green
}

if ($WakeDevices -or $DisableMemoryIntegrity) {
  Write-Host "`nDone. Restart, then leave the PC idle and re-check the sleep/resume log:" -ForegroundColor Cyan
  Write-Host "  if SLEEP is no longer followed by an instant RESUME, it worked." -ForegroundColor Cyan
}
