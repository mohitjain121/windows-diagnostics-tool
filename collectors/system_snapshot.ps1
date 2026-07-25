$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector = 'system_snapshot'
  collected_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated = Test-Elevated
  ok = $true
  error = $null
  data = @()
}
try {
  $os  = Get-CimInstance Win32_OperatingSystem
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  $gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
  $ram = [math]::Round(($os.TotalVisibleMemorySize * 1KB) / 1GB, 1)
  $memUsedPct = [math]::Round(
    (1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 1)
  $uptime = ((Get-Date) - $os.LastBootUpTime).TotalHours
  $sys = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
  $freePct = if ($sys) { [math]::Round(($sys.FreeSpace / $sys.Size) * 100, 1) } else { $null }
  $cpuLoad = (Get-CimInstance Win32_Processor |
    Measure-Object -Property LoadPercentage -Average).Average
  $out.data = @([ordered]@{
    cpu_name = $cpu.Name.Trim()
    gpu_names = $gpu
    ram_total_gb = $ram
    os_caption = $os.Caption
    os_build = $os.BuildNumber
    uptime_hours = [math]::Round($uptime, 1)
    cpu_load_pct = $cpuLoad
    mem_used_pct = $memUsedPct
    system_disk_free_pct = $freePct
  })
} catch {
  $out.ok = $false
  $out.error = $_.Exception.Message
}
$out | ConvertTo-Json -Depth 6 -Compress
