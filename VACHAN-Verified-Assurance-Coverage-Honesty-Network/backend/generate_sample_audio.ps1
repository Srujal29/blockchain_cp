Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$wavPath = "d:\Vortexa\VACHAN-Verified-Assurance-Coverage-Honesty-Network\backend\sales_sample_speech.wav"
$synth.SetOutputToWaveFile($wavPath)
$text = "Hello Mr. Sharma, this is Rohan from InsureChain calling regarding the Care Premier Health Shield policy. This conversation is recorded with your affirmative consent. This policy provides a maximum limit of fifteen lakh rupees with cashless admission across fourteen thousand eight hundred network hospitals. Pre-existing diseases are covered after twenty-four months waiting period, and accident emergency hospitalization is covered from day one."
$synth.Speak($text)
$synth.Dispose()
Write-Host "Audio generated successfully:" (Get-Item $wavPath).Length
