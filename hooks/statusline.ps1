# Windows-native status data collector for Claude Code statusline.
# Called from hooks/statusline-windows.sh roughly every 30s (cached).
#
# Outputs a single pipe-delimited line: cpu|mem|disk|up|tcp
# - cpu:  load percentage, e.g. "34"
# - mem:  used/total in MB, e.g. "6453/32742 MB"
# - disk: C: drive percent used, e.g. "62%"
# - up:   uptime, e.g. "4d 16h" or "2h 39m"
# - tcp:  count of established TCP connections
#
# Dependencies: Windows PowerShell 5+ or PowerShell 7+. No modules required
# beyond CimCmdlets (built-in) and NetTCPIP (built-in since Server 2012 /
# Windows 8). All queries are non-admin.

$os   = Get-CimInstance Win32_OperatingSystem
$cpu  = Get-CimInstance Win32_Processor
$disk = Get-CimInstance Win32_LogicalDisk -Filter 'DeviceID="C:"'
$tcp  = (Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue).Count

$used  = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1024)
$total = [math]::Round($os.TotalVisibleMemorySize / 1024)
$dpct  = [math]::Round(($disk.Size - $disk.FreeSpace) / $disk.Size * 100)

$span  = New-TimeSpan -Start $os.LastBootUpTime -End (Get-Date)
if ($span.Days -gt 0) { $up = "$($span.Days)d $($span.Hours)h" } else { $up = "$($span.Hours)h $($span.Minutes)m" }

Write-Output "$($cpu.LoadPercentage)|$used/$total MB|$dpct%|$up|$tcp"
