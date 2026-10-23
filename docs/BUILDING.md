# Building from the user-supplied ROM

## Windows release for players

Most players should use the precompiled Windows x64 package from GitHub Releases. Extract it, double-click `Shinobi3Recomp.exe`, and select a compatible ROM. The binary already contains the generated native translations; it still reads the user-supplied ROM at runtime for game data and behavior. No developer toolchain is required to run the release package. See [PUBLISHING.md](PUBLISHING.md) for the release allowlist and [README.md](../README.md) for controls and save paths.

## Build from source

This is the supported developer workflow. It requires a 64-bit Windows PC with PowerShell 5.1 or 7, CMake 3.24+, Ninja, Python 3, Zig 0.17.0, and a compatible 1 MiB ROM with SHA-256 `E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3`. The repository does not bundle these tool executables or download them.

Keep the ROM outside the source tree and use an external build directory:

```powershell
./build-windows.ps1 `
    -RomPath 'C:\path\to\your\shinobi3.gen' `
    -BuildDirectory 'C:\path\to\shinobi3-build' `
    -ZigExe 'C:\tools\zig\zig.exe'
```

Omit `-ZigExe` if Zig is on `PATH`. The script checks ROM size and SHA-256 before configuring. It uses CMake's `--fresh`, Release configuration, disables development recorders/tracing/cosimulation/reverse-debugging, regenerates the native C translation from the ROM, compiles the runtime, and prints the executable's SHA-256. The generated code and resulting binary are local ROM-derived outputs; they are not part of the source repository.

The executable is written to `package\Shinobi3Recomp.exe`; `Change-ROM.vbs` is copied beside it. The program remembers a valid selected ROM under `%LOCALAPPDATA%\Shinobi3Recomp\rom-Shinobi3.cfg`. Saves remain under `%LOCALAPPDATA%\Shinobi3Recomp\states` in the established format.

## Generated files

`project/CMakeLists.txt` validates the external ROM and passes it to the bundled recompiler. The generator reads `project/game/game.toml`, discovers code from the ROM, and emits translated C shards, declarations, dispatch, layout/cycle sources, and audit logs under the external build directory. No generated Shinobi C is committed. The Z80 sound CPU is compiled from the runtime's Z80 core; the project does not generate a separate ROM-specific Z80 translation. The ending fix is in runtime scheduling behavior.

## Regressions

```powershell
./test-non-gameplay.ps1 -BuildDirectory 'C:\path\to\shinobi3-build'
```

The script prints the live inventory and excludes all tests labeled `gameplay`; it refuses to proceed if recognized launch tests are missing that label. The verified source candidate passed 37/37 non-gameplay tests, with nine gameplay-launching tests excluded. This is prior verification, not a claim that every future source change has been tested.

## Reproducibility limits

The independent regeneration audit reproduced the accepted generated C byte-for-byte except for a one-byte path-comment length in `shinobi3_layout.c`; the initializer body was identical. The resulting PE differed at 25 bytes across seven short ranges, with build metadata explaining that hashes need not match. The reference regeneration executable SHA-256 is recorded in the build audit. The current GitHub Release executable has not been separately gameplay-verified. See [REGENERATION-AUDIT.md](REGENERATION-AUDIT.md).
