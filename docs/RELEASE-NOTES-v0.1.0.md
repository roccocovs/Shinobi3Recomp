# Shinobi3Recomp — v0.1.0 (proposed initial release)

Shinobi3Recomp is an unofficial native Windows application for *Shinobi III: Return of the Ninja Master*, generated with a modified Matthew Stan Genesis Recompiler and the project's Windows runtime. The executable includes statically translated 68000 game instructions; it also requires a compatible user-supplied ROM for game data and runtime behavior. Not every guest instruction is necessarily executed as generated native code.

## Windows package

The release package is intended for Windows x64. Extract it, launch `Shinobi3Recomp.exe`, and select a legally obtained compatible 1 MiB ROM (SHA-256 `E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3`). The ROM is not included. The app remembers the selected path; `Change-ROM.vbs` opens the picker again.

## Verification status

An earlier accepted build was personally played through all seven rounds, the final boss, ship-crash ending, and into the horseback credits with the interpreter floor disabled. This staged executable is the unchanged output of the independent clean regeneration build and passed the source candidate's previously completed 37/37 non-gameplay CTests; it has not been separately gameplay-tested. The entire post-credits sequence is not verified.

## Known issues

- Minor slowdown has been observed in the Round 1 and final-boss encounters.
- The gameplay impact of a Mijin-related dispatch warning remains unconfirmed.
- Complete post-credits behavior has not been verified.
- The graphical local builder is not implemented; developers building from source need the documented toolchain.

## Source and licensing

Source and build instructions: https://github.com/roccocovs/Shinobi3Recomp. The source repository does not include the ROM, generated Shinobi game C, or executable release asset. Source builds generate these locally from the user's ROM.

The project uses a modified Genesis Recompiler by Matthew Stan. Original contributions are offered under PolyForm Noncommercial 1.0.0 as scoped by the source repository's license. Upstream framework and third-party components keep their separate terms; the package includes applicable notices and license texts. These terms do not grant rights to Sega's game, ROM, trademarks, or audiovisual content. This is an unofficial project and is not affiliated with or endorsed by Sega.
