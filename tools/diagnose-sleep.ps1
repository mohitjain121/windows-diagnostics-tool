#requires -RunAsAdministrator
<#
  Read-only sleep/wake diagnostic. Identifies what is waking the PC out of
  sleep (the "sleep -> instant wake" loop). Changes nothing.
#>
Write-Host "===== ACTIVE WAKE TIMERS (scheduled things that wake the PC) =====" -ForegroundColor Cyan
powercfg /waketimers

Write-Host "`n===== DEVICES ALLOWED TO WAKE THE PC =====" -ForegroundColor Cyan
powercfg /devicequery wake_armed

Write-Host "`n===== WHAT CAUSED THE LAST WAKE =====" -ForegroundColor Cyan
powercfg /lastwake

Write-Host "`n===== RECENT WAKE SOURCES (Kernel-Power 107 resume reasons, last 15) =====" -ForegroundColor Cyan
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=107} -MaxEvents 15 -ErrorAction SilentlyContinue |
  ForEach-Object {
    $x = [xml]$_.ToXml(); $d = @{}; $x.Event.EventData.Data | ForEach-Object { $d[$_.Name] = $_.'#text' }
    "{0} | WakeSourceType={1}" -f $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), $d['WakeSourceType']
  }

Write-Host "`n===== MEMORY INTEGRITY / VBS (forces the hypervisor, breaks AM5 S3 sleep) =====" -ForegroundColor Cyan
$hvci = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' -ErrorAction SilentlyContinue
"Memory Integrity (HVCI) Enabled: $($hvci.Enabled)  (1=on -> this is likely part of the sleep problem)"
