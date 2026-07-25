$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='livekernel_display'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $since = (Get-Date).AddDays(-30)
  $rows = @()
  $filter = @{ LogName='System'; ProviderName='Display'; Id=4101; StartTime=$since }
  $events = Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue
  foreach ($e in $events) {
    $device = 'display'
    $m = [regex]::Match($e.Message, '([A-Za-z0-9_]+)\s+stopped responding')
    if ($m.Success) { $device = $m.Groups[1].Value }
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      device = $device; event_id = $e.Id
    }
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
