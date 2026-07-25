$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='minidump';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@(); $dir=Join-Path $env:windir 'Minidump'
  if (Test-Path $dir) {
    foreach ($f in (Get-ChildItem $dir -Filter *.dmp -ErrorAction SilentlyContinue)) {
      $rows += [ordered]@{ when=$f.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ'); filename=$f.Name; bugcheck_code=$null }
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
