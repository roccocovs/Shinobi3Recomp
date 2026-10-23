[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $BuildDirectory
)

$ErrorActionPreference = 'Stop'
$build = (Resolve-Path -LiteralPath $BuildDirectory).Path
$ctest = Get-Command ctest -ErrorAction SilentlyContinue
if (-not $ctest) { throw "ctest was not found on PATH. Install CMake before running the regression suite." }

$jsonText = (& $ctest.Source --test-dir $build --show-only=json-v1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the CTest inventory ($LASTEXITCODE)." }
$inventory = $jsonText | ConvertFrom-Json
$allNames = @($inventory.tests | ForEach-Object { $_.name })
$gameplayNames = @($inventory.tests | Where-Object {
    $labels = @($_.properties | Where-Object { $_.name -eq 'LABELS' } | ForEach-Object { $_.value })
    ($labels -contains 'gameplay') -or ($labels -contains 'launches-game')
} | ForEach-Object { $_.name })

$knownLaunchers = @($allNames | Where-Object { $_ -match '^(ShinobiRun|ShinobiExpert|ShinobiDuck|ShinobiDoubleJump)' })
$unlabeledLaunchers = @($knownLaunchers | Where-Object { $_ -notin $gameplayNames })
if ($unlabeledLaunchers.Count) {
    throw "Refusing to run tests that may launch gameplay but lack gameplay labels: $($unlabeledLaunchers -join ', ')"
}
if (-not $gameplayNames.Count) {
    throw 'No gameplay tests were labeled. Inspect the test inventory before running CTest.'
}

Write-Output "Registered CTests: $($allNames.Count)"
Write-Output "Excluded gameplay-launching tests ($($gameplayNames.Count)): $($gameplayNames -join ', ')"
Write-Output "Running $($allNames.Count - $gameplayNames.Count) non-gameplay tests."
& $ctest.Source --test-dir $build --output-on-failure --parallel -LE gameplay
if ($LASTEXITCODE -ne 0) { throw "Non-gameplay CTest suite failed ($LASTEXITCODE)." }
