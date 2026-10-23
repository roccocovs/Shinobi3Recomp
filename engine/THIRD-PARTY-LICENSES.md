
## Framework dependencies

| Component | Role | License | Source |
|---|---|---|---|
| **ymfm** (`runner/external/ymfm/`) | YM2612 FM synthesis in native releases | BSD-3-Clause | <https://github.com/aaronsgiles/ymfm> |
| **superzazu/z80** (`runner/external/superzazu/`) | Z80 sound-CPU core in native releases | MIT | <https://github.com/superzazu/z80> |
| **clowncommon** (`runner/external/clowncommon/`) | Integer types and small C helpers | ISC | <https://github.com/Clownacy/clowncommon> |
| **minicoro** (`runner/external/minicoro/`) | Game-fiber context switch | Unlicense OR MIT-0; embedded context-switch assembly derives from LuaCoco (MIT, Mike Pall) | <https://github.com/edubart/minicoro> |
| **SDL2** (`runner/external/SDL2/`) | Windowing, input, rendering, audio delivery | zlib | <https://libsdl.org> |
| **tomlc99** (`recompiler/src/toml.{c,h}`) | TOML parsing for configuration | MIT | <https://github.com/cktan/tomlc99> |
| **recomp-net** (`external/recomp-net/`) | Optional netplay transport and lobby support | MIT | <https://github.com/TechnicallyComputers/recomp-net> |
| **rbengine** (`external/rbengine/`) | Required runner snapshot and monotonic-clock helpers | MIT | `external/rbengine/LICENSE` |
| **ShadowVerifier and color-science core** (`runner/audio/audio_shadow.{c,h}`, `runner/video/color_lut.{c,h}`) | Optional audio/video verification and color science | MIT OR Apache-2.0, used with permission | <https://github.com/JRickey/gba-recomp> and the gbarecomp/snesrecomp ports |

License texts are retained with the vendored or submodule sources:

- `runner/external/ymfm/LICENSE`
- `runner/external/superzazu/LICENSE`
- `runner/external/clowncommon/LICENCE.txt`
- `runner/external/minicoro/LICENSE`, plus the LuaCoco MIT notice embedded in
  `runner/external/minicoro/minicoro.h`
- `runner/external/SDL2/SDL2-2.28.5/COPYING.txt`
- the MIT notice embedded at the top of `recompiler/src/toml.c` and `toml.h`
- `external/recomp-net/LICENSE`
- `external/rbengine/LICENSE` (including copyright and full MIT text)
- The ShadowVerifier/color-science source attribution is in each source file;
  the upstream terms are MIT OR Apache-2.0 as recorded there.
- `m68k-recomp-core` and `z80-recomp-core` carry their own license and
  provenance files.

## Game repository launcher dependencies

Game repositories normally add the shared `recomp-ui` launcher at build time;
it is not vendored here. A release enabling it must also preserve notices and
assets for Dear ImGui, stb helpers, tinyfiledialogs, and Lato from that revision.

## Compliance notes

- The executable Release package carries applicable notices and license texts.
- The shipped binary must not contain the ROM image; users supply it separately.
- The executable does contain generated translations of ROM instructions. The
  project license does not grant rights to third-party game code.
- This inventory is informational, not legal advice.
