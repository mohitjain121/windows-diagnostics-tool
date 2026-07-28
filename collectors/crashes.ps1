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
    $row = [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      kind = $kind; event_id = $e.Id
      source = $e.ProviderName; bugcheck_code = $null
      message = ($e.Message -split "`n")[0].Trim()
    }
    if ($e.Id -eq 1001) {
      $m = [regex]::Match($e.Message, '0x[0-9A-Fa-f]{8}')
      if ($m.Success) { $row.bugcheck_code = '0x' + [Convert]::ToInt32($m.Value,16).ToString('x') }
    }
    if ($e.Id -eq 41) {
      try {
        $x = [xml]$e.ToXml(); $d = @{}
        foreach ($p in $x.Event.EventData.Data) { $d[$p.Name] = $p.'#text' }
        if ($d.ContainsKey('SleepInProgress')) { $row.sleep_in_progress = [int]$d['SleepInProgress'] }
        if ($d.ContainsKey('PowerButtonTimestamp')) { $row.power_button = [int64]$d['PowerButtonTimestamp'] }
      } catch {}
    }
    if ($e.Id -eq 6008) {
      # Properties[0]=time string, [1]=date string (localized); combine via Get-Date.
      try {
        $ts = $e.Properties[0].Value; $ds = $e.Properties[1].Value
        $actual = Get-Date ("$ds $ts")
        $row.actual_when = $actual.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        $row.actual_local_hour = $actual.Hour
      } catch {}
    }
    $rows += $row
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
