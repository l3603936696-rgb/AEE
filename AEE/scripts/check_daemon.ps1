# Check daemon status via HTTP
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8765/status" -TimeoutSec 5
    $response.Content
} catch {
    Write-Host "Daemon not responding: $_"
}

# Check log file
$f = Get-Item "E:\XIA\logs\daemon_live.log"
Write-Host "LastWriteTime: $($f.LastWriteTime)"
Write-Host "Length: $($f.Length)"
Write-Host "Last 3 lines:"
$allLines = [System.IO.File]::ReadAllLines("E:\XIA\logs\daemon_live.log")
$lastLines = $allLines | Select-Object -Last 3
$lastLines
