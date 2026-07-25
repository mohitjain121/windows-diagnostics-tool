$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='storage_smart';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@()
  foreach ($d in (Get-PhysicalDisk -ErrorAction SilentlyContinue)) {
    $rc = $d | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
    $pf = $false
    try { $pf = ($d.HealthStatus -ne 'Healthy') } catch {}
    $rows += [ordered]@{
      model=$d.FriendlyName
      wear_pct=$(if($rc){$rc.Wear}else{$null})
      reallocated_sectors=$null
      read_errors=$(if($rc){$rc.ReadErrorsTotal}else{$null})
      write_errors=$(if($rc){$rc.WriteErrorsTotal}else{$null})
      temperature_c=$(if($rc){$rc.Temperature}else{$null})
      predictive_failure=$pf
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
