$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='updates';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@(); $since=(Get-Date).AddDays(-60)
  $noise='KB2267602|Defender|Security Intelligence|Antivirus|Antimalware'
  $searcher=(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
  $count=$searcher.GetTotalHistoryCount()
  if ($count -gt 0) {
    foreach ($h in $searcher.QueryHistory(0,[math]::Min($count,100))) {
      if ($h.Date -ge $since -and $h.Title -and ($h.Title -notmatch $noise)) {
        $kb=[regex]::Match($h.Title,'KB\d+')
        $rows += [ordered]@{ when=([datetime]$h.Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); name=$(if($kb.Success){$kb.Value}else{$h.Title}); version=$null }
      }
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
