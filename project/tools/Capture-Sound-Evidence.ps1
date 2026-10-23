param(
    [int]$Port = 4382,
    [int]$RecentWrites = 100000,
    [string]$OutputRoot = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

if ($RecentWrites -lt 1) { throw 'RecentWrites must be positive.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path $OutputRoot "sound-evidence-$stamp"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$client = [System.Net.Sockets.TcpClient]::new()
$client.ReceiveTimeout = 15000
$client.SendTimeout = 15000
$reader = $null
$writer = $null
$script:requestId = 0

function Invoke-TraceCommand {
    param([string]$Name, [hashtable]$Arguments = @{})

    $script:requestId++
    $request = [ordered]@{ id = $script:requestId; cmd = $Name }
    foreach ($key in $Arguments.Keys) { $request[$key] = $Arguments[$key] }
    $writer.WriteLine(($request | ConvertTo-Json -Compress))
    $line = $reader.ReadLine()
    if ([string]::IsNullOrWhiteSpace($line)) {
        throw "No response for trace command '$Name'."
    }
    $response = $line | ConvertFrom-Json
    if ($response.ok -eq $false) {
        throw "Trace command '$Name' failed: $($response.error)"
    }
    return $response
}

try {
    $client.Connect('127.0.0.1', $Port)
    $stream = $client.GetStream()
    $stream.ReadTimeout = 15000
    $stream.WriteTimeout = 15000
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 4096, $true)
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false), 4096, $true)
    $writer.AutoFlush = $true

    $registers = Invoke-TraceCommand 'get_registers'
    $crashTrail = Invoke-TraceCommand 'crash_trail'
    $audioStats = Invoke-TraceCommand 'audio_stats'
    $ring = Invoke-TraceCommand 'rdb_count'
    $soundReads = Invoke-TraceCommand 'sound_index_trace' @{ start = 0; count = 256 }
    if ($null -eq $soundReads.first_invalid) {
        throw 'This capture script requires the first-fault diagnostic build.'
    }
    $soundReads.first_invalid | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir 'first-invalid-sound-jump.json')
    $readAddresses = @{}
    foreach ($event in $soundReads.log) { $readAddresses[[string]$event.adr] = $true }
    if ($soundReads.first_invalid.present) { $readAddresses[[string]$soundReads.first_invalid.adr] = $true }
    $soundReads | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir 'sound-index-trace.json')

    $registers | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir 'registers-at-capture.json')
    $crashTrail | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir 'crash-trail.json')
    $audioStats | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir 'audio-stats.json')
    $ring | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir 'write-ring-status.json')

    # A5 is recorded as a contemporaneous clue. Preserve the complete WRAM
    # history window as well, because A5 may have changed since the sound read.
    $a5 = [uint64]$registers.A5
    $candidateAddress = ($a5 + 0x1F) -band 0xFFFFFF
    $candidateText = ('0x{0:X6}' -f $candidateAddress)
    $historyPath = Join-Path $outDir 'wram-write-history.jsonl'
    $candidatePath = Join-Path $outDir 'sound-byte-candidate-writes.jsonl'
    $readAddressPath = Join-Path $outDir 'sound-byte-read-address-writes.jsonl'
    $start = [Math]::Max(0, [int64]$ring.count - $RecentWrites)
    $end = [int64]$ring.count
    $pageSize = 48
    $saved = 0
    $candidateSaved = 0
    $readAddressSaved = 0
    $writerFile = [System.IO.StreamWriter]::new($historyPath, $false, [System.Text.UTF8Encoding]::new($false))
    $candidateFile = [System.IO.StreamWriter]::new($candidatePath, $false, [System.Text.UTF8Encoding]::new($false))
    $readAddressFile = [System.IO.StreamWriter]::new($readAddressPath, $false, [System.Text.UTF8Encoding]::new($false))
    try {
        for ($offset = $start; $offset -lt $end;) {
            $take = [int][Math]::Min($pageSize, $end - $offset)
            $page = Invoke-TraceCommand 'rdb_dump' @{ start = [int]$offset; count = $take }
            if (-not $page.log -or $page.returned -le 0) { break }
            foreach ($entry in $page.log) {
                $json = $entry | ConvertTo-Json -Depth 5 -Compress
                $writerFile.WriteLine($json)
                $saved++
                if ($readAddresses.ContainsKey([string]$entry.adr)) {
                    $readAddressFile.WriteLine($json)
                    $readAddressSaved++
                }
                if ([string]$entry.adr -ieq $candidateText) {
                    $candidateFile.WriteLine($json)
                    $candidateSaved++
                }
            }
            $offset += [int64]$page.returned
        }
    }
    finally {
        $writerFile.Dispose()
        $candidateFile.Dispose()
        $readAddressFile.Dispose()
    }

    $deliveryPath = ((Join-Path $outDir 'audio-delivery.txt') -replace '\\', '/')
    $delivery = Invoke-TraceCommand 'audio_delivery_dump' @{ path = $deliveryPath }
    $delivery | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $outDir 'audio-delivery-result.json')

    @"
Sound evidence capture: $stamp
WRAM writer entries saved: $saved
Sound dispatch events saved: $($soundReads.returned)
First invalid sound dispatch preserved: $($soundReads.first_invalid.present)
Writes to addresses observed at the sound dispatch: $readAddressSaved
Sound-byte candidate address from live A5 + 0x1F: $candidateText
Writes to that candidate address in captured window: $candidateSaved

first-invalid-sound-jump.json preserves the first invalid native table index
at 069BB0 or 069BCA, plus up to 32 preceding writes to its byte address
(newest first), sampled from a separate 4096-entry sound-workspace ring.
That ring covers FFF800-FFFAFF. It may lack older writes or writes outside
that region. Function/caller attribution is recorded, not an exact writer
instruction PC. It does not establish native/interpreter divergence.
sound-index-trace.json records the latest 256 native dispatches at both sites,
including read-time A5, effective byte address, byte value, and jump target.
sound-byte-read-address-writes.jsonl contains retained writes matching those
addresses. Compare frames and values to identify the writer; address matches
alone do not establish which write supplied a read. Only WRAM writes are
recorded, and older writes can roll out of the ring. Each downloaded page
uses a fresh ring snapshot; an actively running game can shift that window.
The separate candidate file uses A5 at capture time and is only a clue.
Each writer entry contains frame, address, value, native function, and caller.
Audio delivery data is in audio-delivery.txt; live mixer stats are in
audio-stats.json. This script only queries existing rings; it does not pause
or change game inputs.
"@ | Set-Content -Encoding UTF8 (Join-Path $outDir 'README.txt')

    Write-Output "Sound evidence saved to: $outDir"
}
finally {
    if ($writer) { $writer.Dispose() }
    if ($reader) { $reader.Dispose() }
    $client.Dispose()
}
