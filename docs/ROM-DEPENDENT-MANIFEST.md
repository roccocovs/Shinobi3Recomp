# ROM-dependent inputs and outputs

This manifest distinguishes the public GitHub source tree from the separate Windows Release package.

| Category | Example | Handling |
|---|---|---|
| User-supplied ROM | Compatible 1 MiB `shinobi3.gen` image | Not included in source or Release. Selected at runtime; source builds validate it and do not modify it. |
| ROM-specific technical configuration | `project/game/game.toml`, `project/game/shinobi3_spec.c` | Included in source by the author's decision. These provide functional addresses, selectors, aliases, and integration; they do not contain generated instruction streams or game assets. |
| Generated ROM translation | `shinobi3_part*.c`, declarations, dispatch, layout/cycle sources | Created locally under the external build directory. Not committed or distributed as source files. |
| Compiled native executable | `Shinobi3Recomp.exe` | Separately distributed as a GitHub Release asset under the user's Option A decision. It contains statically translated ROM-derived 68000 instructions and requires the compatible user ROM at runtime. |
| Runtime dependency | `SDL2.dll` and Windows system libraries | The SDL2 DLL is staged with the Release; operating-system DLLs are supplied by supported Windows. |
| Development artifacts | PDBs, objects, logs, diagnostics, build manifests | Excluded from the public source tree and end-user Release package. |
| Original, upstream, and third-party code | Recompiler/runtime and dependencies | Preserve each component's applicable license and notices. The project license does not replace upstream or third-party terms. |
| Private research and saves | Disassemblies, captures, save-state files, historical folders | Excluded from source and Release. |

The complete source inventory is `PUBLIC-SOURCE-INVENTORY.txt`. Release contents are inventoried separately in the staged package's `README.txt` and the release-preparation report. The `.gitignore` is not a substitute for reviewing actual files.
