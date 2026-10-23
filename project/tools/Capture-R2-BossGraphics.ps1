[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('entry', 'corruption')]
    [string]$Label
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$resultsRoot = Join-Path $projectRoot 'results'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$nonce = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$captureDir = Join-Path $resultsRoot "r2-boss-graphics-$Label-$stamp-$nonce"
$null = New-Item -ItemType Directory -Path $captureDir -Force

$script:requestId = 0
$manifest = [ordered]@{
    status = 'starting'
    label = $Label
    capturedUtc = [DateTime]::UtcNow.ToString('o')
    server = '127.0.0.1:4382'
    readOnlyCommands = @('frame_info', 'vdp_state', 'read_vram', 'read_ram', 'vdp_events')
    frameBefore = $null
    frameAfter = $null
    files = @()
    failure = $null
}

function Invoke-LocalTraceCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [hashtable]$Arguments = @{}
    )

    $client = New-Object System.Net.Sockets.TcpClient
    $stream = $null
    $reader = $null
    $writer = $null
    try {
        $client.ReceiveTimeout = 10000
        $client.SendTimeout = 5000
        $client.Connect([System.Net.IPAddress]::Parse('127.0.0.1'), 4382)
        $stream = $client.GetStream()
        $stream.ReadTimeout = 10000
        $stream.WriteTimeout = 5000
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 4096, $true)
        $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false), 4096, $true)
        $writer.AutoFlush = $true

        $script:requestId++
        $expectedId = $script:requestId
        $request = [ordered]@{ id = $expectedId; cmd = $Name }
        foreach ($key in $Arguments.Keys) { $request[$key] = $Arguments[$key] }
        $writer.WriteLine(($request | ConvertTo-Json -Compress))
        $line = $reader.ReadLine()
        if ([string]::IsNullOrWhiteSpace($line)) { throw "No response for '$Name'." }

        try { $response = $line | ConvertFrom-Json }
        catch { throw "Invalid JSON response for '$Name': $($_.Exception.Message)" }
        if ($null -eq $response.id -or [int]$response.id -ne $expectedId) {
            throw "Response ID mismatch for '$Name' (expected $expectedId)."
        }
        if ($response.ok -ne $true) {
            $serverError = if ($response.error) { [string]$response.error } else { 'server returned ok=false' }
            throw "Read-only command '$Name' failed: $serverError"
        }
        return $response
    }
    finally {
        if ($writer) { $writer.Dispose() }
        if ($reader) { $reader.Dispose() }
        if ($client) { $client.Dispose() }
    }
}

function Assert-HexPayload {
    param([string]$Hex, [int]$ByteCount, [string]$Name)
    if ($null -eq $Hex -or $Hex.Length -ne ($ByteCount * 2) -or $Hex -notmatch '\A[0-9A-Fa-f]*\z') {
        throw "'$Name' returned an invalid hex payload; expected $ByteCount bytes."
    }
}

function Save-JsonFile {
    param([string]$Name, [object]$Value)
    $path = Join-Path $captureDir $Name
    $json = ConvertTo-Json -InputObject $Value -Depth 8
    [System.IO.File]::WriteAllText($path, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    $manifest.files += $Name
}

function Read-HexRange {
    param([string]$Address, [int]$ByteCount, [string]$Command)
    $builder = New-Object System.Text.StringBuilder ($ByteCount * 2)
    $baseAddress = [Convert]::ToInt32(($Address -replace '^0x', ''), 16)
    for ($offset = 0; $offset -lt $ByteCount; ) {
        $chunkSize = [Math]::Min(4096, $ByteCount - $offset)
        $chunkAddress = '0x{0:X4}' -f ($baseAddress + $offset)
        $response = Invoke-LocalTraceCommand $Command @{ addr = $chunkAddress; size = $chunkSize }
        if ([int]$response.size -ne $chunkSize) { throw "$Command at $chunkAddress returned the wrong byte count." }
        Assert-HexPayload ([string]$response.hex) $chunkSize "$Command at $chunkAddress"
        [void]$builder.Append([string]$response.hex)
        $offset += $chunkSize
    }
    return $builder.ToString()
}

try {
    $before = Invoke-LocalTraceCommand 'frame_info'
    if ($null -eq $before.current_frame) { throw 'frame_info did not return current_frame before capture.' }
    $manifest.frameBefore = [long]$before.current_frame

    # One VDP snapshot captures CRAM/VSRAM and the VDP registers/SAT base.
    # VRAM and object RAM are then read in bounded, read-only chunks.
    $vdp = Invoke-LocalTraceCommand 'vdp_state' @{ include = 'cram,vsram' }
    if ($null -eq $vdp.vdp -or $null -eq $vdp.vdp.sprite_table) { throw 'vdp_state response is missing VDP registers or the sprite-table base.' }
    if ($null -eq $vdp.vdp.cram -or $vdp.vdp.cram.Count -ne 64) { throw 'vdp_state did not return all 64 CRAM entries.' }
    if ($null -eq $vdp.vdp.vsram -or $vdp.vdp.vsram.Count -ne 64) { throw 'vdp_state did not return all 64 VSRAM entries.' }
    Save-JsonFile 'vdp-state.json' $vdp

    $vramHex = Read-HexRange '0x0000' 65536 'read_vram'
    [System.IO.File]::WriteAllText((Join-Path $captureDir 'vram.hex'), $vramHex, [System.Text.Encoding]::ASCII)
    $manifest.files += 'vram.hex'
    $manifest.vramBytes = 65536

    # Raw object pool and list roots help identify the boss slot without relying
    # on the diagnostic scanner's linked-list walk.
    $objectPoolHex = Read-HexRange '0xFF4182' 6048 'read_ram'
    Save-JsonFile 'object-pool.json' ([ordered]@{ address = '0xFF4182'; bytes = 6048; hex = $objectPoolHex })
    $objectRootsHex = Read-HexRange '0xFF5E6C' 148 'read_ram'
    Save-JsonFile 'object-roots.json' ([ordered]@{ address = '0xFF5E6C'; bytes = 148; hex = $objectRootsHex })

    $events = Invoke-LocalTraceCommand 'vdp_events' @{ count = 256 }
    if ($null -eq $events.events -or $null -eq $events.emitted) { throw 'vdp_events response is missing its event list or emitted count.' }
    Save-JsonFile 'vdp-events.json' $events

    $after = Invoke-LocalTraceCommand 'frame_info'
    if ($null -eq $after.current_frame) { throw 'frame_info did not return current_frame after capture.' }
    $manifest.frameAfter = [long]$after.current_frame
    $manifest.status = 'complete'
}
catch {
    $manifest.status = 'failed'
    $manifest.failure = [string]$_.Exception.Message
}
finally {
    $manifest.completedUtc = [DateTime]::UtcNow.ToString('o')
    $manifestPath = Join-Path $captureDir 'capture-manifest.json'
    $manifestJson = ConvertTo-Json -InputObject $manifest -Depth 8
    [System.IO.File]::WriteAllText($manifestPath, $manifestJson + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

Write-Output "Capture folder: $captureDir"
if ($manifest.status -eq 'complete') {
    Write-Output "Label: $Label; guest frames: $($manifest.frameBefore) to $($manifest.frameAfter)."
    Write-Output 'Read-only capture complete; inspect capture-manifest.json for files and status.'
}
else {
    Write-Error "Capture failed: $($manifest.failure). Any completed files and the failure are recorded in $captureDir."
    exit 1
}
