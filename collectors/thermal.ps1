$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='thermal';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@()
  $since=(Get-Date).AddDays(-30)
  $ev = Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Kernel-Processor-Power';StartTime=$since} -ErrorAction SilentlyContinue |
        Where-Object { $_.Id -in 86,87,88 }
  foreach ($e in $ev) {
    $rows += [ordered]@{ type='event'; when=$e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');
                         kind='throttle'; source=$e.ProviderName; detail=(($e.Message -split "`n")[0].Trim()) }
  }
  # Best-effort ACPI zone temperature (deci-Kelvin -> Celsius). Often unavailable.
  try {
    $tz = Get-CimInstance -Namespace root/WMI -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop
    foreach ($z in $tz) {
      $c = [math]::Round(($z.CurrentTemperature / 10.0) - 273.15, 1)
      $rows += [ordered]@{ type='temp'; name='ACPI thermal zone'; value=$c; unit='C' }
    }
  } catch {}
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
