param(
    [string]$BuildDirectory = 'build-recreated'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$package = Join-Path $projectRoot (Join-Path $BuildDirectory 'package')
$exe = Join-Path $package 'Shinobi3Recomp.exe'
$rom = Join-Path $package 'shinobi3.gen'
$inputScript = Join-Path $PSScriptRoot 'options-menu.input'
$screenshot = Join-Path $package 'options-menu-after-confirm.png'

foreach ($path in @($exe, $rom, $inputScript)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required Options-menu test file is missing: $path"
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
    $env:GENESIS_FLOOR = '0'
    $env:GENESIS_SHINOBI_EXPERT_CONTROLS = '1'
    Push-Location $projectRoot
    try {
        & $exe $rom --input-script $inputScript --max-frames 1000
        if ($LASTEXITCODE -ne 0) {
            throw "Options-menu gameplay script failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $screenshot)) {
        throw "Options-menu screenshot was not created: $screenshot"
    }

    Add-Type -AssemblyName System.Drawing
    $image = [System.Drawing.Image]::FromFile($screenshot)
    try {
        $visiblePixels = 0
        for ($y = 0; $y -lt $image.Height; $y++) {
            for ($x = 0; $x -lt $image.Width; $x++) {
                $pixel = $image.GetPixel($x, $y)
                if ($pixel.R -gt 8 -or $pixel.G -gt 8 -or $pixel.B -gt 8) {
                    $visiblePixels++
                }
            }
        }
        if ($visiblePixels -lt 1000) {
            throw "Options screen remained blank ($visiblePixels non-black pixels)."
        }

        if ($image.Width -ne 320 -or $image.Height -ne 224) {
            throw "Unexpected Options screenshot size: $($image.Width)x$($image.Height)."
        }
        $highlightWhitePixels = 0
        for ($y = 40; $y -lt 48; $y++) {
            for ($x = 128; $x -lt 168; $x++) {
                $pixel = $image.GetPixel($x, $y)
                if ($pixel.R -ge 220 -and $pixel.G -ge 220 -and $pixel.B -ge 220) {
                    $highlightWhitePixels++
                }
            }
        }
        if ($highlightWhitePixels -lt 100) {
            throw "Selected Options text is still being darkened ($highlightWhitePixels bright-white pixels; expected at least 100)."
        }
        Write-Output "Options menu passed: $visiblePixels visible pixels; selected text has $highlightWhitePixels bright-white pixels."
    }
    finally {
        $image.Dispose()
    }
}
finally {
    foreach ($name in $oldEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $oldEnv[$name], 'Process')
    }
}
