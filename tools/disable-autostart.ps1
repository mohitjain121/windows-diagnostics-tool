#requires -RunAsAdministrator
<#
  Reversible auto-start reducer. Boot bloat (too many background services and
  startup apps) is a common cause of general lag and a stuttering browser.
  This sets chosen background services to Manual or Disabled and can turn off
  Fast Startup. Nothing is uninstalled. Reverse with enable-autostart.ps1.

  You supply the target service name / display-name patterns (regex). Find
  candidates with:  Get-Service | Sort-Object Status

  Examples:
    # Send two services to on-demand start, disable one unused one, Fast Startup off
    .\disable-autostart.ps1 -ManualServices 'VendorTool','ContainerRuntime' `
                            -DisableServices 'UnusedVpn' -DisableFastStartup

    # Just turn Fast Startup off
    .\disable-autostart.ps1 -DisableFastStartup
#>
param(
  [string[]]$ManualServices  = @(),   # patterns -> set to Manual (start on demand)
  [string[]]$DisableServices = @(),   # patterns -> set to Disabled (fully off)
  [switch]$DisableFastStartup
)
$ErrorActionPreference = 'Stop'

if (-not $ManualServices -and -not $DisableServices -and -not $DisableFastStartup) {
  Write-Host "Nothing to do. Pass -ManualServices / -DisableServices patterns and/or -DisableFastStartup." -ForegroundColor Yellow
  Write-Host "See the header of this script for examples." -ForegroundColor Yellow
  return
}

$svcs = Get-CimInstance Win32_Service
function Set-Svc([string]$pattern, [string]$type) {
  $hits = $svcs | Where-Object {
    $_.DisplayName -match $pattern -or $_.Name -match $pattern -or $_.PathName -match $pattern
  }
  if (-not $hits) { Write-Host "  (no service matched '$pattern')" -ForegroundColor DarkGray; return }
  foreach ($s in $hits) {
    try {
      if ($s.State -eq 'Running') { Stop-Service -Name $s.Name -Force -ErrorAction SilentlyContinue }
      Set-Service -Name $s.Name -StartupType $type
      Write-Host ("  [{0,-9}] {1}" -f $type, $s.DisplayName) -ForegroundColor Green
    } catch {
      Write-Host ("  ! skipped {0}: {1}" -f $s.DisplayName, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
}

foreach ($p in $DisableServices) { Set-Svc $p 'Disabled' }
foreach ($p in $ManualServices)  { Set-Svc $p 'Manual' }

if ($DisableFastStartup) {
  Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' `
    -Name HiberbootEnabled -Value 0
  Write-Host "  [OFF      ] Fast Startup" -ForegroundColor Green
}

Write-Host "`nDone. Also review Task Manager (Ctrl+Shift+Esc) > Startup apps and disable" -ForegroundColor Cyan
Write-Host "anything you don't need at boot, then restart." -ForegroundColor Cyan
