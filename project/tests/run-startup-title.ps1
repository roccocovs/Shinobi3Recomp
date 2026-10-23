param(
    [ValidateSet('0', '1')]
    [string]$Floor = '0'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$package = Join-Path $projectRoot 'build-recreated/package'
$exe = Join-Path $package 'Shinobi3Recomp.exe'
$rom = Join-Path $package 'shinobi3.gen'
$script = Join-Path $PSScriptRoot 'startup-title.input'

foreach ($path in @($exe, $rom, $script)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required startup test file is missing: $path"
    }
}

$oldEnv = @{}
foreach ($name in @('LNG_SCRIPT', 'LNG_TEST_HIDDEN', 'GENESIS_FORCE_INTERP', 'GENESIS_FLOOR', 'GENESIS_SHINOBI_EXPERT_CONTROLS')) {
    $oldEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $env:LNG_SCRIPT = '1'
    $env:LNG_TEST_HIDDEN = '1'
    $env:GENESIS_FORCE_INTERP = '0'
    $env:GENESIS_FLOOR = $Floor
    [Environment]::SetEnvironmentVariable('GENESIS_SHINOBI_EXPERT_CONTROLS',$null,'Process')
    & $exe $rom --input-script $script --max-frames 500
    if ($LASTEXITCODE -ne 0) {
        throw "Startup callback test failed with exit code $LASTEXITCODE"
    }
}
finally {
    foreach ($name in $oldEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $oldEnv[$name], 'Process')
    }
}

Write-Output "Startup callback test passed (GENESIS_FLOOR=$Floor)."
