$word = New-Object -ComObject Word.Application
$word.Visible = $false
$doc = $word.Documents.Open("d:\QQ文件\情绪设计.docx")
$text = $doc.Content.Text
$doc.Close()
$word.Quit()
Write-Output $text
