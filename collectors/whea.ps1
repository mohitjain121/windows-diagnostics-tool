$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='whea';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $since=(Get-Date).AddDays(-30); $rows=@()
  $ev=Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger';StartTime=$since} -ErrorAction SilentlyContinue
  foreach ($e in $ev) {
    $sev = switch ($e.Id) { {$_ -in 17,47} {'corrected'} {$_ -in 18,19} {'uncorrected'} default {'informational'} }
    $rows += [ordered]@{ when=$e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); severity=$sev; error_source=(($e.Message -split "`n")[0].Trim()); event_id=$e.Id }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
