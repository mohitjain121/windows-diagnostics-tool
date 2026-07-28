# collectors/memory_config.ps1
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='memory_config';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $dimms = @(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue)
  if ($dimms.Count -gt 0) {
    $rated = ($dimms | Measure-Object -Property Speed -Maximum).Maximum
    $configured = ($dimms | Measure-Object -Property ConfiguredClockSpeed -Maximum).Maximum
    $part = ($dimms[0].PartNumber | ForEach-Object { $_.Trim() })
    $out.data = @([ordered]@{
      dimm_count = $dimms.Count
      rated_mts = [int]$rated
      configured_mts = [int]$configured
      part_number = "$part"
    })
  }
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
