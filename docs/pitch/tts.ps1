param([string]$Dir)
Add-Type -AssemblyName System.Speech
$items = Get-Content -Raw -Encoding UTF8 (Join-Path $Dir "narration.json") | ConvertFrom-Json
foreach ($it in $items) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice("Microsoft Hazel Desktop")
  $s.Rate = 0
  $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(44100, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
  $s.SetOutputToWaveFile((Join-Path $Dir ("vo_" + $it.scene + ".wav")), $fmt)
  # "provenum" read as one word
  $s.Speak(($it.text -replace "provenum", "pro venum"))
  $s.Dispose()
}
