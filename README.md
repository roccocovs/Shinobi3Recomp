# Shinobi III Native Recompilation

Shinobi3Recomp is an unofficial native Windows recompilation of *Shinobi III: Return of the Ninja Master*, built with Matthew Stan's Genesis Recompiler and a modified runtime. The Windows release contains statically translated 68000 game instructions and loads a compatible ROM supplied by the user for game data and runtime behavior. The hybrid runtime also retains interpretation for some dynamic execution paths; this does not mean every guest instruction runs as generated native code.

## Play the Windows release

1. Download the Windows x64 asset from the repository's GitHub Releases page and extract the folder.
2. Double-click `Shinobi3Recomp.exe`.
3. Select your legally obtained compatible ROM when prompted.
4. Play. The app remembers a valid ROM path under `%LOCALAPPDATA%\Shinobi3Recomp\rom-Shinobi3.cfg`. Double-click `Change-ROM.vbs` beside the executable to select a different ROM later.

The release does not include a ROM. The supported image is 1 MiB with SHA-256 `E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3`. The executable requires that ROM at runtime; a file picker does not make it ROM-independent.

## Build from source

Developers may clone this source repository, provide the compatible ROM locally, and follow [the Windows build guide](docs/BUILDING.md). The build generates game C and a playable executable locally. The source repository does not commit the ROM, generated Shinobi C, or compiled executable.

## Project status

An earlier accepted native-first build was played through all seven rounds, the final boss, the ship-crash ending, and into the horseback credits with `GENESIS_FLOOR=0`. Complete post-credits behavior was not verified. The source candidate independently regenerated matching game C and passed 37/37 non-gameplay CTests. The current GitHub Release executable is copied unchanged from that clean regeneration build and has not received a separate interactive gameplay verification.

## Controls and saves

Keyboard and gamepad inputs are enabled. Arrow keys move; `Z`, `X`, `C` map to Genesis A/B/C; `Enter` is Start; `A`, `S`, `D` map to X/Y/Z; `Backspace` is Mode; `Tab` is turbo. Six-button controller mapping is enabled by default. `F1`–`F9` load the matching save slot, and `Shift+F1`–`Shift+F9` save. Save files are in `%LOCALAPPDATA%\Shinobi3Recomp\states`.

## Known limitations

- Minor slowdown has been observed during the Round 1 and final-boss encounters.
- A Mijin-related dispatch warning was observed; its gameplay impact remains unverified.
- The full post-credits sequence has not been verified.
- A graphical local build utility is not implemented. Source builds require the toolchain in [docs/BUILDING.md](docs/BUILDING.md).

## Architecture

This is not a traditional cycle-by-cycle console emulator. The recompiler translates configured 68000 routines from the supplied ROM into C at build time. The Windows binary contains those generated translations alongside the runtime, CPU/audio components, and integration code. Some dynamic/interior execution paths retain hybrid interpretation. The Z80 sound processor runs through the included runtime core, with the project-specific bus-request/mailbox scheduling correction.

## Attribution and licensing

This project uses a modified [Sega Genesis Recompiler](https://github.com/mstan/segagenesisrecomp) by **Matthew Stan**. Copyright and licensing for his work remain with him under the existing PolyForm Noncommercial terms. Original contributions by roccocovs are offered under PolyForm Noncommercial 1.0.0 as scoped in [LICENSE.md](LICENSE.md); this is not an exclusive license for the entire repository. Third-party components retain their separate terms listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). The executable includes ROM-derived translated instructions, and no project license grants rights to Sega game content.

*Shinobi III: Return of the Ninja Master*, its ROM, trademarks, and audiovisual content belong to Sega and/or the applicable rights holders. This unofficial fan project is not affiliated with or endorsed by Sega. No Sega permission is claimed. The source-only repository and binary release are separate: the source tree omits generated game C and the ROM, while the Release executable contains generated game instructions and still requires the user's ROM.

## Documentation

- [Build from source](docs/BUILDING.md)
- [Release publishing and package contents](docs/PUBLISHING.md)
- [ROM-dependent output manifest](docs/ROM-DEPENDENT-MANIFEST.md)
- [Redistribution review](docs/REDISTRIBUTION-REVIEW.md)
- [Comparison with Matthew Stan's public Sonic recompilation](docs/UPSTREAM-PRACTICES-COMPARISON.md)
- [Proposed v0.1.0 release notes](docs/RELEASE-NOTES-v0.1.0.md)
