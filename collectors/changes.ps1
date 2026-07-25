$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='changes'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $since = (Get-Date).AddDays(-60)
  $rows = @()

  # Software install/update/uninstall from Program-Inventory operational log.
  $pi = Get-WinEvent -FilterHashtable @{
    LogName='Microsoft-Windows-Application-Experience/Program-Inventory'
    Id=@(903,904,905,906); StartTime=$since } -ErrorAction SilentlyContinue
  foreach ($e in $pi) {
    $ct = switch ($e.Id) { 903 {'install'} 904 {'update'} 905 {'uninstall'} 906 {'uninstall'} default {'install'} }
    $name = ($e.Message -split "`n")[0].Trim()
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      change_type = $ct; name = $name; version = $null; source = 'program-inventory'
    }
  }

  # MSI installs/removals from Application log.
  $msi = Get-WinEvent -FilterHashtable @{
    LogName='Application'; ProviderName='MsiInstaller'; Id=@(11707,11724); StartTime=$since
  } -ErrorAction SilentlyContinue
  foreach ($e in $msi) {
    $ct = if ($e.Id -eq 11724) { 'uninstall' } else { 'install' }
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      change_type = $ct; name = (($e.Message -split "`n")[0].Trim()); version = $null; source = 'msi'
    }
  }

  # Driver installs from setupapi.dev.log (parse install sections).
  $log = Join-Path $env:windir 'INF\setupapi.dev.log'
  if (Test-Path $log) {
    $lines = Get-Content $log -ErrorAction SilentlyContinue
    for ($i=0; $i -lt $lines.Count; $i++) {
      if ($lines[$i] -match '>>>\s+\[Device Install .*\]') {
        $tsMatch = $null
        for ($j=$i+1; $j -lt [math]::Min($i+4,$lines.Count); $j++) {
          $tm = [regex]::Match($lines[$j], '>>>\s+Section start (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})')
          if ($tm.Success) { $tsMatch = $tm.Groups[1].Value; break }
        }
        if ($tsMatch) {
          $dt = [datetime]::ParseExact($tsMatch,'yyyy/MM/dd HH:mm:ss',$null)
          if ($dt -ge $since) {
            $nm = [regex]::Match($lines[$i], '\[Device Install \(.*?\) - (.*?)\]')
            $devName = $(if($nm.Success){$nm.Groups[1].Value}else{''})
            # Keep only real driver-package installs (an .INF), not device-instance
            # enumerations (BTHENUM\, PCI\VEN, SWD\DRIVERENUM, hdaudio\...).
            if ($devName -match '\.inf$') {
              $rows += [ordered]@{
                when = $dt.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
                change_type = 'driver'; name = (Split-Path $devName -Leaf)
                version = $null; source = 'setupapi'
              }
            }
          }
        }
      }
    }
  }

  # OS updates from Windows Update history. Skip high-frequency noise
  # (Defender/antivirus definition updates) that would swamp correlation.
  $noise = 'KB2267602|Defender|Security Intelligence|Antivirus|Antimalware'
  try {
    $searcher = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
    $count = $searcher.GetTotalHistoryCount()
    if ($count -gt 0) {
      $hist = $searcher.QueryHistory(0, [math]::Min($count,100))
      foreach ($h in $hist) {
        if ($h.Date -ge $since -and $h.Title -and ($h.Title -notmatch $noise)) {
          $kb = [regex]::Match($h.Title, 'KB\d+')
          $rows += [ordered]@{
            when = ([datetime]$h.Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            change_type = 'os_update'
            name = ($(if($kb.Success){$kb.Value}else{$h.Title})); version = $null; source = 'windows-update'
          }
        }
      }
    }
  } catch {}

  # Deduplicate identical (timestamp, name) entries, newest first.
  $seen = @{}
  $deduped = @()
  foreach ($r in ($rows | Sort-Object when -Descending)) {
    $key = "$($r.when)|$($r.name)"
    if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; $deduped += $r }
  }
  $out.data = @($deduped)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
