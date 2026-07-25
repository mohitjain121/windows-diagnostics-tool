#requires -RunAsAdministrator
<#
  Undo for disable-autostart.ps1 - restores the given services to Automatic
  start and can turn Fast Startup back on. (Re-enable any startup APPS you
  turned off in Task Manager > Startup apps separately.)

  Example:
    .\enable-autostart.ps1 -Services 'VendorTool','ContainerRuntime','UnusedVpn' -EnableFastStartup
#>
param(
  [string[]]$Services = @(),   # patterns -> set back to Automatic
  [switch]$EnableFastStartup
)
$ErrorActionPreference = 'Stop'

$svcs = Get-CimInstance Win32_Service
function Set-Svc([string]$pattern, [string]$type) {
  $hits = $svcs | Where-Object {
    $_.DisplayName -match $pattern -or $_.Name -match $pattern -or $_.PathName -match $pattern
  }
  foreach ($s in $hits) {
    try {
      Set-Service -Name $s.Name -StartupType $type
      Write-Host ("  [{0}] {1}" -f $type, $s.DisplayName) -ForegroundColor Green
    } catch {
      Write-Host ("  ! skipped {0}: {1}" -f $s.DisplayName, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
}

foreach ($p in $Services) { Set-Svc $p 'Automatic' }

if ($EnableFastStartup) {
  Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' `
    -Name HiberbootEnabled -Value 1
  Write-Host "  Fast Startup re-enabled" -ForegroundColor Green
}
Write-Host "`nRestored. Restart to apply." -ForegroundColor Cyan
