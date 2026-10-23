param([ValidateSet('0','1')][string]$Floor = '0')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$package = Join-Path $root 'build-recreated/package'
$log = Join-Path $package "startup-gameplay-floor$Floor.log"
$names = @('LNG_SCRIPT','LNG_TEST_HIDDEN','GENESIS_FORCE_INTERP','GENESIS_FLOOR','GENESIS_SHINOBI_EXPERT_CONTROLS','SDL_AUDIODRIVER')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
try {
    $env:LNG_SCRIPT = '1'
    $env:LNG_TEST_HIDDEN = '1'
    $env:GENESIS_FORCE_INTERP = '0'
    $env:GENESIS_FLOOR = $Floor
    [Environment]::SetEnvironmentVariable('GENESIS_SHINOBI_EXPERT_CONTROLS',$null,'Process')
    $env:SDL_AUDIODRIVER = 'dummy'
    foreach ($file in @('gameplay_before.ram','gameplay_after.ram')) {
        $path = Join-Path $package $file
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
    $stdout = "$log.stdout"
    $stderr = "$log.stderr"
    $process = Start-Process -FilePath (Join-Path $package 'Shinobi3Recomp.exe') `
        -ArgumentList @((Join-Path $package 'shinobi3.gen'), '--input-script',
            (Join-Path $PSScriptRoot 'startup-gameplay.input'), '--max-frames', '1500', '--turbo') `
        -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    @((Get-Content -LiteralPath $stdout), (Get-Content -LiteralPath $stderr)) | Set-Content -LiteralPath $log
    Remove-Item -LiteralPath $stdout, $stderr -ErrorAction SilentlyContinue
    if ($process.ExitCode -ne 0) { throw "Gameplay test exited $($process.ExitCode); see $log" }
    if (Select-String -LiteralPath $log -Pattern '^(\[dispatch\] interior-label miss:|dispatch miss:|\[ILLEGAL\]|\[FLOOR\].*(declined|UNSAFE)|\[GAME\].*unexpected)') {
        throw "Runtime dispatch failed; see $log"
    }
    $before = [IO.File]::ReadAllBytes((Join-Path $package 'gameplay_before.ram'))
    $after = [IO.File]::ReadAllBytes((Join-Path $package 'gameplay_after.ram'))
    if ($before.Length -ne 65536 -or $after.Length -ne 65536) { throw 'Incomplete RAM capture' }
    # Joe is the first object at FF412E; +20 is the world X coordinate.
    if (($before[0x412E] -band 0x80) -eq 0 -or ($after[0x412E] -band 0x80) -eq 0) { throw 'Joe did not spawn or disappeared' }
    $xBefore = 256 * $before[0x414E] + $before[0x414F]
    $xAfter = 256 * $after[0x414E] + $after[0x414F]
    if ($xAfter -le $xBefore) { throw "Joe did not move right: $xBefore -> $xAfter" }
    Write-Output "Cold-boot gameplay passed: Joe moved $xBefore -> $xAfter; floor=$Floor; no dispatch failures."
}
finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$previous[$name],'Process') }
}
