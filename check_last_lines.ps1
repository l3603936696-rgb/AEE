$f = [System.IO.File]::OpenRead("E:\XIA\logs\daemon_live.log")
$s = New-Object System.IO.StreamReader($f, [System.Text.Encoding]::UTF8)
$lines = @()
while (($l = $s.ReadLine()) -ne $null) { $lines += $l }
$s.Close()
$f.Close()
$lines[-5..-1]
