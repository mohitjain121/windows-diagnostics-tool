$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='crashes'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $since = (Get-Date).AddDays(-30)
  $rows = @()
  $filter = @{ LogName='System'; Id=@(41,1001,6008); StartTime=$since }
  $events = Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue
  foreach ($e in $events) {
    $kind = switch ($e.Id) { 41 {'unexpected_shutdown'} 1001 {'bugcheck'} 6008 {'dirty_shutdown'} default {'unknown'} }
    $bc = $null
    if ($e.Id -eq 1001) {
      $m = [regex]::Match($e.Message, '0x[0-9A-Fa-f]{8}')
      if ($m.Success) { $bc = '0x' + [Convert]::ToInt32($m.Value,16).ToString('x') }
    }
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      kind = $kind; event_id = $e.Id
      source = $e.ProviderName; bugcheck_code = $bc
      message = ($e.Message -split "`n")[0].Trim()
    }
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
