param(
    [string]$BuildDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'build-recreated')
)

$ErrorActionPreference = 'Stop'
$exe = Join-Path $BuildDir 'ShinobiControllerProfileTest.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Controller profile test executable is missing: $exe"
}

$stdout = Join-Path $BuildDir 'controller-profile.stdout.txt'
$stderr = Join-Path $BuildDir 'controller-profile.stderr.txt'
$process = Start-Process -FilePath $exe -Wait -PassThru -NoNewWindow `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
if ($process.ExitCode -ne 0) {
    if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr }
    throw "Controller profile test exited $($process.ExitCode)."
}

Get-Content -LiteralPath $stdout
