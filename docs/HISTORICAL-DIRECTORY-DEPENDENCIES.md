# Historical directory dependency audit

The candidate was built and tested with a new, empty build directory. The CMake cache and generated build graph identify only the candidate's own `project/` and `engine/` trees, the supplied ROM path, and installed toolchain paths. The PowerShell build script derives project, engine, and compiler-wrapper paths from its own `$PSScriptRoot`; it does not search sibling candidates or prior build folders. A source-wide scan found no absolute references to the original development profile or historical candidate/build paths.

Generated translation shards and the executable were created in the new external build directory. The generated source comparison against the accepted build was read-only. No prior candidate or build output was copied into the new build.

## What a future build requires

Retain the new source candidate, a compatible user-supplied ROM, and a compatible installed build toolchain. The generated build directory is an output/cache and is not required to rebuild; it can be deleted and recreated. The accepted gameplay-tested source/build pair is a rollback reference until the user interactively verifies the freshly regenerated executable, but it is not a dependency of this candidate.

The scripts tested here require PowerShell, CMake, Ninja, Python 3, and Zig 0.17.0. The candidate does not bundle these tools. This is not yet a graphical one-click builder.

## Cleanup interpretation

Once the freshly regenerated executable has passed the user's gameplay check, old round-by-round source candidates, their build directories, and the former standalone-release staging directory are technically removable if the user no longer wants historical rollback points. None is a build input. Keep any analysis archive or save/checkpoint directory the user values; this build audit does not establish that private research is disposable. No cleanup outside this candidate was performed.
