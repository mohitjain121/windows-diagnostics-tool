$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='reliability';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@()
  $recs=Get-CimInstance Win32_ReliabilityRecords -ErrorAction SilentlyContinue
  foreach ($r in $recs) {
    # SourceName 'Microsoft-Windows-WindowsUpdateClient' failure records map to failed updates.
    $ct=$null
    if ($r.SourceName -like '*WindowsUpdate*' -and $r.message -match 'fail') { $ct='update' }
    if ($ct) {
      $tg = $r.TimeGenerated
      if ($tg -isnot [datetime]) { $tg = [Management.ManagementDateTimeConverter]::ToDateTime([string]$tg) }
      $when = $tg.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      $rows += [ordered]@{ when=$when; change_type=$ct; name=$r.ProductName; version=$null }
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
