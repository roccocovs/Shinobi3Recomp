# Architecture and provenance

The build uses the Genesis Recompiler toolchain in `engine/` and the game-specific ROM configuration in `project/game/game.toml`. During a local build, the generator reads the ROM supplied through `SHINOBI_ROM_PATH`, translates configured 68000 routines into generated C under the build directory, then compiles those sources together with the runtime. The configuration and generated C contain ROM-derived information and are not automatically cleared for redistribution; see `REDISTRIBUTION-REVIEW.md`.

The Windows runtime owns input, save-state I/O, audio delivery, and Genesis VDP/bus/Z80 scheduling. Most known ROM paths in the verified game are compiled native code. The runner retains its 68000 interpreter for dynamic or interior dispatch misses and explicit developer modes. `GENESIS_FORCE_INTERP=1` can force whole-program interpretation; the normal default is native-first and `GENESIS_FLOOR` defaults off for this game. The Z80 is interpreted by the included `superzazu/z80` runtime; this project does not generate a separate ROM-specific Z80 translation. The ending-progression repair is in runtime Z80 bus-request/mailbox scheduling and is covered by `R7EndingZ80Handshake`.

The Z80 bus-request handshake correction is part of the accepted baseline and is covered by `R7EndingZ80Handshake`. Round-specific callbacks and continuation fixes are retained in `game.toml` and the associated synthetic tests. These tests do not replace interactive gameplay verification.

The generated code and executable are ROM-derived. Omitting the input ROM from the source folder and package does not resolve rights in generated translations or game logic. See [Redistribution review](REDISTRIBUTION-REVIEW.md).
