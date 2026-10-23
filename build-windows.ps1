[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $RomPath,
    [string] $BuildDirectory = (Join-Path $PSScriptRoot 'build'),
    [string] $ZigExe
)

$ErrorActionPreference = 'Stop'
$expectedHash = 'E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3'
$rom = (Resolve-Path -LiteralPath $RomPath).Path
$romInfo = Get-Item -LiteralPath $rom
if ($romInfo.Length -ne 1048576) {
    throw "The supported Shinobi III ROM must be exactly 1 MiB; found $($romInfo.Length) bytes."
}
$actualHash = (Get-FileHash -LiteralPath $rom -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) {
    throw "ROM SHA-256 mismatch. Expected $expectedHash; found $actualHash."
}

function Find-Tool([string] $Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) { throw "Required build tool '$Name' was not found on PATH. See README.md for the tested toolchain." }
    return $command.Source
}

$cmake = Find-Tool 'cmake'
$ninja = Find-Tool 'ninja'
$null = Find-Tool 'python'
if (-not $ZigExe) { $ZigExe = Find-Tool 'zig' }
else { $ZigExe = (Resolve-Path -LiteralPath $ZigExe).Path }
$env:ZIG_EXE = $ZigExe
$env:PATH = "$(Split-Path -Parent $ZigExe);$env:PATH"

$project = Join-Path $PSScriptRoot 'project'
$engine = Join-Path $PSScriptRoot 'engine'
$cc = Join-Path $PSScriptRoot 'tools\zig-cc.cmd'
$cxx = Join-Path $PSScriptRoot 'tools\zig-cxx.cmd'
$build = [System.IO.Path]::GetFullPath($BuildDirectory)
New-Item -ItemType Directory -Path $build -Force | Out-Null
$zigCache = Join-Path $build 'zig-cache'
New-Item -ItemType Directory -Path $zigCache -Force | Out-Null
$env:ZIG_LOCAL_CACHE_DIR = Join-Path $zigCache 'local'
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $zigCache 'global'
New-Item -ItemType Directory -Path $env:ZIG_LOCAL_CACHE_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $env:ZIG_GLOBAL_CACHE_DIR -Force | Out-Null

& $cmake --fresh -S $project -B $build -G Ninja `
    "-DCMAKE_MAKE_PROGRAM=$ninja" `
    "-DCMAKE_BUILD_TYPE=Release" `
    "-DCMAKE_C_COMPILER=$cc" `
    "-DCMAKE_CXX_COMPILER=$cxx" `
    "-DGENESIS_RECOMP_ROOT=$engine" `
    "-DSHINOBI_ZIG_EXE=$ZigExe" `
    "-DSHINOBI_ROM_PATH=$rom" `
    '-DSHINOBI_ENABLE_DEV_DIAGNOSTICS=OFF' `
    '-DSHINOBI_ENABLE_TRACE=OFF' `
    '-DSHINOBI_ENABLE_COSIM=OFF' `
    '-DSHINOBI_ENABLE_REVERSE_DEBUG=OFF'
if ($LASTEXITCODE -ne 0) { throw "CMake configuration failed ($LASTEXITCODE)." }

& $cmake --build $build --config Release --parallel
if ($LASTEXITCODE -ne 0) { throw "Release build failed ($LASTEXITCODE)." }

$exe = Join-Path $build 'package\Shinobi3Recomp.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Build completed without the expected executable: $exe" }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Change-ROM.vbs') `
    -Destination (Join-Path $build 'package\Change-ROM.vbs') -Force
Write-Output "Release executable: $exe"
Write-Output "SHA-256: $((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash)"
