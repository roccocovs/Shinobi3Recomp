# Third-party notices

This project combines independently authored project contributions, the Genesis Recompiler, and separately licensed libraries. The top-level `LICENSE.md` applies PolyForm Noncommercial 1.0.0 only to roccocovs's original contributions. Matthew Stan's Genesis Recompiler work remains under its existing terms in `engine/`; third-party dependencies retain their own licenses. Preserve all listed license and notice files.

| Component | Use in this tree | License / notice location |
|---|---|---|
| Genesis Recompiler framework and recompiler components | ROM translation and runtime | `engine/LICENSE.md`, `engine/LICENSE-recompiler` — PolyForm Noncommercial 1.0.0 |
| m68k-recomp-core, z80-recomp-core | Shared CPU/recompiler components | Their `engine/external/*/LICENSE` and provenance files; PolyForm Noncommercial 1.0.0 |
| rbengine | Required runner/runtime utility | `engine/external/rbengine/LICENSE` — MIT |
| SDL2 2.28.5 | Window, video, input, audio | `engine/runner/external/SDL2/SDL2-2.28.5/COPYING.txt` — zlib |
| ymfm | YM2612 FM sound | `engine/runner/external/ymfm/LICENSE` — BSD-3-Clause |
| superzazu/z80 | Z80 sound CPU | `engine/runner/external/superzazu/LICENSE` — MIT |
| clowncommon | Common C definitions/helpers | `engine/runner/external/clowncommon/LICENCE.txt` — ISC |
| minicoro and LuaCoco | Fiber switching and embedded context-switch assembly | `engine/runner/external/minicoro/LICENSE`; LuaCoco MIT attribution is embedded in `minicoro.h` |
| tomlc99 | TOML parsing | MIT notice in `engine/recompiler/src/toml.c` and `toml.h` |
| recomp-net | Optional networking source, not enabled in this game release | `engine/external/recomp-net/LICENSE` — MIT |
| ShadowVerifier / color-science core | Optional audio/video validation and color science | MIT OR Apache-2.0, used with permission; attribution is in source files and terms are recorded in `engine/THIRD-PARTY-LICENSES.md` |

This summary does not replace the license files. The top-level license covers only roccocovs's original contributions. Matthew Stan and other contributors retain their own copyrights and licenses. No listed license grants rights to Sega's game or ROM. See `docs/REDISTRIBUTION-REVIEW.md` for scope and limitations.

The separate Windows Release package repeats applicable license texts under `licenses/` and includes a package-specific notice summary. The release binary is not part of the public source inventory.
