$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$resultsRoot = Join-Path $projectRoot 'results'
$loggerPath = Join-Path $PSScriptRoot 'log-burst-audio.py'
$python = (Get-Command python -ErrorAction Stop).Source
$null = New-Item -ItemType Directory -Path $resultsRoot -Force
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$captureDir = Join-Path $resultsRoot "live-sound-capture-$stamp"
$null = New-Item -ItemType Directory -Path $captureDir
$sessionPath = Join-Path $captureDir 'capture-session.json'
$csvPath = Join-Path $captureDir 'live-sound.csv'
$sidecarPath = Join-Path $captureDir 'sound-block-snapshots.jsonl'
$wavPath = Join-Path $captureDir 'game-audio.wav'
$script:requestId = 0
$wavStarted = $false
$loggerExitCode = 0
$session = [ordered]@{
    status = 'starting'; createdLocal = (Get-Date).ToString('o'); host = '127.0.0.1'; port = 4382
    captureDir = $captureDir; csv = $csvPath; sidecar = $sidecarPath; wav = $wavPath
}

function Invoke-LocalTraceCommand {
    param([string]$Name, [hashtable]$Arguments = @{})
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $client.ReceiveTimeout = 8000; $client.SendTimeout = 5000
        $client.Connect('127.0.0.1', 4382)
        $stream = $client.GetStream(); $stream.ReadTimeout = 8000; $stream.WriteTimeout = 5000
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 4096, $true)
        $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false), 4096, $true)
        $writer.AutoFlush = $true; $script:requestId++
        $request = [ordered]@{ id = $script:requestId; cmd = $Name }
        foreach ($key in $Arguments.Keys) { $request[$key] = $Arguments[$key] }
        $writer.WriteLine(($request | ConvertTo-Json -Compress))
        $line = $reader.ReadLine()
        if ([string]::IsNullOrWhiteSpace($line)) { throw "No response for $Name." }
        $response = $line | ConvertFrom-Json
        if ($response.ok -eq $false) { throw "Trace command $Name failed: $($response.error)" }
        return $response
    }
    finally { $client.Dispose() }
}

try {
    $frame = Invoke-LocalTraceCommand 'frame_info'
    if ($null -eq $frame.current_frame) { throw 'frame_info did not return current_frame.' }
    $wavStatus = Invoke-LocalTraceCommand 'audio_wav' @{ action = 'status' }
    if ($wavStatus.active) { throw 'A WAV capture is already active; stop it before starting another capture.' }
    $null = Invoke-LocalTraceCommand 'audio_wav' @{ action = 'start'; path = $wavPath }
    $wavStarted = $true
    $session['status'] = 'active'; $session['startGuestFrame'] = [int]$frame.current_frame
    ConvertTo-Json -InputObject $session | Set-Content -LiteralPath $sessionPath -Encoding UTF8
    Write-Host "Sound capture folder: $captureDir"
    Write-Host 'Logger is in this window: press Enter after a sound glitch; press Ctrl+C to stop and finalize the WAV.'

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python -u $loggerPath --host 127.0.0.1 --port 4382 --output $csvPath `
            --sound-snapshots $sidecarPath --event-dir $captureDir --stop-wav-on-exit
        $loggerExitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
}
finally {
    if ($wavStarted) {
        try {
            $status = Invoke-LocalTraceCommand 'audio_wav' @{ action = 'status' }
            if ($status.active) { $null = Invoke-LocalTraceCommand 'audio_wav' @{ action = 'stop' } }
        }
        catch { $session['fallbackStopError'] = [string]$_ }
    }
    $session['status'] = 'stopped'; $session['stoppedLocal'] = (Get-Date).ToString('o')
    $session['loggerExitCode'] = $loggerExitCode
    ConvertTo-Json -InputObject $session | Set-Content -LiteralPath $sessionPath -Encoding UTF8
}

Write-Output "Sound capture saved in: $captureDir"
if ($loggerExitCode -ne 0) { throw "Sound logger exited with code $loggerExitCode; inspect the capture folder." }
