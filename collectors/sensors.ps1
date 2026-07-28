# collectors/sensors.ps1  (opt-in; loads LibreHardwareMonitorLib if present)
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='sensors';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $dll = Join-Path $PSScriptRoot '..\tools\LibreHardwareMonitorLib.dll'
  if (-not (Test-Path $dll)) {
    $out.error = 'LibreHardwareMonitorLib.dll not found; deep sensors skipped'
    $out | ConvertTo-Json -Depth 6 -Compress; return
  }
  Add-Type -Path $dll
  $computer = New-Object LibreHardwareMonitor.Hardware.Computer
  $computer.IsCpuEnabled = $true; $computer.IsGpuEnabled = $true
  $computer.IsMotherboardEnabled = $true; $computer.IsMemoryEnabled = $true
  $computer.Open()
  $rows=@()
  foreach ($hw in $computer.Hardware) {
    $hw.Update()
    foreach ($sh in $hw.SubHardware) { $sh.Update() }
    foreach ($s in $hw.Sensors) {
      if ($null -eq $s.Value) { continue }
      $kind = switch ("$($s.SensorType)") { 'Temperature' {'temp'} 'Fan' {'fan'} 'Voltage' {'voltage'} 'Clock' {'clock'} default {$null} }
      if ($null -eq $kind) { continue }
      $unit = switch ($kind) { 'temp' {'C'} 'fan' {'RPM'} 'voltage' {'V'} 'clock' {'MHz'} }
      $rows += [ordered]@{ name="$($hw.Name) $($s.Name)"; kind=$kind; value=[math]::Round([double]$s.Value,2); unit=$unit }
    }
  }
  $computer.Close()
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
