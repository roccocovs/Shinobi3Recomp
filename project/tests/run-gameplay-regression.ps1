param(
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$Rom,
    [Parameter(Mandatory=$true)][string]$InputScript,
    [Parameter(Mandatory=$true)][ValidateSet('0','1')][string]$Floor,
    [Parameter(Mandatory=$true)][ValidateSet('0','1')][string]$SixButtonProfile
)

$ErrorActionPreference = 'Stop'
$runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$work = Join-Path (Split-Path -Parent $Exe) "test-artifacts\grounded-floor$Floor-sixbutton$SixButtonProfile-$runId"
New-Item -ItemType Directory -Force -Path $work | Out-Null

$names = @('GENESIS_FORCE_INTERP','GENESIS_FLOOR','GENESIS_SHINOBI_EXPERT_CONTROLS',
           'SDL_AUDIODRIVER','LNG_TEST_HIDDEN','LNG_SCRIPT')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

try {
    $env:GENESIS_FORCE_INTERP = '0'
    $env:GENESIS_FLOOR = $Floor
    $env:GENESIS_SHINOBI_EXPERT_CONTROLS = $SixButtonProfile
    $env:SDL_AUDIODRIVER = 'dummy'
    $env:LNG_TEST_HIDDEN = '1'
    $env:LNG_SCRIPT = '1'

    Push-Location $work
    try {
        $stdoutPath = Join-Path $work 'run.stdout.log'
        $stderrPath = Join-Path $work 'run.stderr.log'
        $quotedRom = '"' + $Rom + '"'
        $quotedScript = '"' + $InputScript + '"'
        $process = Start-Process -FilePath $Exe `
            -ArgumentList @($quotedRom, '--input-script', $quotedScript,
                '--benchmark', '2400') `
            -WorkingDirectory $work -PassThru -Wait -NoNewWindow `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $exitCode = $process.ExitCode
        $stdoutText = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -Raw -LiteralPath $stdoutPath } else { '' }
        $stderrText = if (Test-Path -LiteralPath $stderrPath) { Get-Content -Raw -LiteralPath $stderrPath } else { '' }
        Set-Content -LiteralPath (Join-Path $work 'run.log') -Value ($stdoutText + [Environment]::NewLine + $stderrText)
    }
    finally { Pop-Location }

    if ($exitCode -ne 0) { throw "Gameplay run exited $exitCode; see $work\run.log" }
    if (Select-String -LiteralPath (Join-Path $work 'run.log') -Pattern '^\[(ILLEGAL|TRAP|GAME)\]') {
        throw "Gameplay run reported a guest trap; see $work\run.log"
    }
    if (Select-String -LiteralPath (Join-Path $work 'run.log') -Pattern '^\[dispatch\] interior-label miss: \$(020B28|020D12|020D18|020D2E|020D34|020F02|000C5C|0018A2|001E88|024B5E|024D38|024EB2|02512A|025158|02517E|0251EE|025214|0251BE|025254|0252D4|0252E4|0254C4|0254D8|025580|0255B4)\b') {
        throw "Gameplay run fell back at a native action/object-handler entry; see $work\run.log"
    }
    Write-Output "PASS: scripted gameplay assertions passed (floor=$Floor, six-button-profile=$SixButtonProfile). Artifacts: $work"
}
finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}


