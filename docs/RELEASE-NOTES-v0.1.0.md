# Shinobi3Recomp — v0.1.0 (Initial Windows Release)

Shinobi3Recomp is an unofficial native Windows application for *Shinobi III: Return of the Ninja Master*, generated with a modified Matthew Stan Genesis Recompiler and the project's Windows runtime. The executable includes statically translated 68000 game instructions; it also requires a compatible user-supplied ROM for game data and runtime behavior. Not every guest instruction is necessarily executed as generated native code.

## Windows package

The release package is intended for Windows x64. Extract it, launch `Shinobi3Recomp.exe`, and select a legally obtained compatible 1 MiB ROM (SHA-256 `E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3`). The ROM is not included. The app remembers the selected path; `Change-ROM.vbs` opens the picker again.

## Verification status

Shinobi3Recomp is fully playable from beginning to end. All seven rounds and the complete ending sequence have been verified during development testing.

The v0.1.0 executable has also been successfully tested on a separate Windows 11 laptop, confirming functional graphics, audio, keyboard controls, and DualSense controller support. This was a portability and gameplay test, not a second full playthrough.

The source candidate previously passed all 37 non-gameplay regression tests, with nine gameplay-launching tests excluded.

## Known issues

- A Mijin-related dispatch warning was observed; its gameplay impact remains unverified.
- A graphical local build utility is not implemented. Building from source requires the documented development toolchain.

Minor compatibility, performance, or timing differences from original Sega Genesis hardware may remain.


## Source and licensing

Source and build instructions: https://github.com/roccocovs/Shinobi3Recomp. The source repository does not include the ROM, generated Shinobi game C, or executable release asset. Source builds generate these locally from the user's ROM.

The project uses a modified Genesis Recompiler by Matthew Stan. Original contributions are offered under PolyForm Noncommercial 1.0.0 as scoped by the source repository's license. Upstream framework and third-party components keep their separate terms; the package includes applicable notices and license texts. These terms do not grant rights to Sega's game, ROM, trademarks, or audiovisual content. This is an unofficial project and is not affiliated with or endorsed by Sega.
