$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("C:\Users\Administrator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\XIA.lnk")
$Shortcut.TargetPath = "python"
$Shortcut.Arguments = "-m AEE.src.daemon.daemon --http-port 8765"
$Shortcut.WorkingDirectory = "E:\XIA\AEE"
$Shortcut.WindowStyle = 7
$Shortcut.Save()
Write-Host "快捷方式已创建"
