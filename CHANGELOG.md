# Changelog

## 0.1.0 — proposed initial release

- Provides a source repository and a separate precompiled Windows x64 release package. Both workflows require the user to supply a compatible ROM; the Windows executable includes statically translated 68000 game instructions.
- Source builds generate translated game code locally; the source repository does not include the ROM, generated Shinobi C, or compiled game executable.
- Preserves the accepted seven-round native-first behavior and Z80 bus-handshake correction in the source baseline.
- Replaces unnecessary copied actual-ROM instruction/data snippets in regression tests with supported-ROM validation and semantic control-flow, dispatch, and generated-code assertions. Synthetic generic recompiler fixtures remain.
- Adds the required `rbengine` MIT attribution and excludes the unused historical `code_generator.c.pea-before` backup.
- A clean external Windows build succeeded and all 37 non-gameplay CTests passed. The earlier accepted executable was played through the seven rounds, final boss, ship-crash ending, and into the horseback credits; the staged release executable has not received a separate interactive gameplay verification. Complete post-credits behavior remains unverified.

Original contributions by roccocovs use PolyForm Noncommercial 1.0.0 within the scope stated in `LICENSE.md`. Matthew Stan's framework and third-party components retain their own terms. The project is unofficial and not affiliated with or endorsed by Sega.
