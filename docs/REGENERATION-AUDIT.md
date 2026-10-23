# Clean regeneration audit

## Result

The candidate was configured and built from its own `project/` and `engine/` directories into a newly created external build directory. The only game input was the user-supplied supported ROM at the path passed to `build-windows.ps1`. No generated game C, executable, or object file was copied from a previous build tree.

The generator read a 1 MiB ROM with the supported SHA-256, loaded `project/game/game.toml`, emitted all 280 configured function entries, found 39 additional routines, completed code generation without unsupported codegen operations, and produced the generated code in the external build tree. It emitted 32 C shards, declarations, dispatch/layout/cycle sources, and generation audit data. The source tree contains no generated `shinobi3_part*.c` files.

Compared with the prior public-release-candidate build's generated output, 37 of 38 generated files were byte-identical. The only difference was one extra byte in a generated path comment in `shinobi3_layout.c`; its initializer body matched. Compared with that same reference executable, both files were 8,499,200 bytes and PE `.text` matched exactly (7,813,120 bytes); 25 differences occurred in seven short ranges outside `.text`, including build metadata/identifier data. The executable hashes therefore differ, but that reference's native code section is byte-identical.

The latest clean build's executable SHA-256 is `291DCA577C056A39EAC1AD47C38DA36C3ACC4005C4B315376621640CC525BE14`. Re-run the documented build before release; build metadata can change the final hash. The clean candidate passed all 37 non-gameplay CTests. The Z80 ending handshake has a focused passing regression; the `glue.c` scheduling implementation is byte-identical to the accepted Z80-handshake source. The executable was not compared byte-for-byte with the earlier gameplay-tested Z80-handshake executable, whose file size differs. Therefore interactive verification of this freshly regenerated build is required before replacing or deleting that rollback pair. No game or emulator was launched.

## Dependency boundaries

- Required build inputs: this source tree, the exact user-supplied ROM, CMake, Ninja, Python 3, and Zig 0.17.0.
- The audit used CMake 4.3.5, Ninja 1.13.1, Python 3.14.7, and Zig 0.17.0 from a separate local tools folder. The candidate does not bundle these tools or download them.
- CMake's configured source roots point to this candidate's `project/` and `engine/`; the configured ROM is the external user input. No cache or source file points to a historical candidate/build folder.
- Generated C, audit logs, PDBs, objects, executable and intermediate files belong in the selected external build directory and must remain local.
- The repo build script is portable in its source/build relationship: it resolves `project/`, `engine/`, and compiler wrappers relative to `$PSScriptRoot`. It accepts the ROM and build paths as inputs.

## Limits

This proves technical regeneration for the audited ROM and toolchain; it does not establish rights to distribute `game.toml`, generated translations, the executable, or upstream components. It does not prove bit-identical output from all compiler versions or interactive correctness of the freshly generated executable. The graphical ROM-select/build utility is not implemented. Users currently need PowerShell and the documented toolchain.
