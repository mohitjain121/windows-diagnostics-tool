$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='drivers'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $rows = @()
  $drivers = Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
    Where-Object { $_.DeviceName -and $_.DriverVersion }
  foreach ($d in $drivers) {
    $inst = $null
    if ($d.DriverDate) {
      try { $inst = ([datetime]$d.DriverDate).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } catch {}
    }
    $rows += [ordered]@{
      name = $d.DeviceName; version = $d.DriverVersion
      provider = $d.DriverProviderName; install_date = $inst
      device_class = $d.DeviceClass
    }
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
