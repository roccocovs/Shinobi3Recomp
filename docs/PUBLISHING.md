# Publication handoff

This project publishes two distinct artifacts: a source repository and a precompiled Windows x64 application in GitHub Releases. The source tree omits the original ROM, generated Shinobi game C, and compiled game executable. The Release package contains a compiled executable with statically translated ROM-derived 68000 instructions; it does not contain the ROM and still requires the user's compatible ROM at runtime.

## GitHub source repository

Publish the reviewed source candidate as `roccocovs/Shinobi3Recomp`. The root contains the recompiler/runtime source, third-party dependencies and notices, configuration, build/test scripts, and documentation. Review `PUBLIC-SOURCE-INVENTORY.txt` and the final Git index. `.gitignore` helps exclude local outputs but does not determine provenance.

The author selected PolyForm Noncommercial 1.0.0 for original contributions and authorized publication of the audited ROM technical metadata. `LICENSE.md` scopes this to the author's contributions. Preserve Matthew Stan's framework licensing and all third-party notices. The source inventory and license scope do not grant rights to Sega material or ROM-derived executable output.

## GitHub Release asset

The Windows package is a separate downloadable Release asset; do not commit it to the source repository. Stage only the executable, the required SDL2 runtime DLL, ROM-changing helper, user README, and applicable license/notice files. Exclude the ROM, generated C, PDBs, diagnostic TOML files, build manifests, saves, and development artifacts. The executable still reads a compatible ROM selected by the user and contains translated game instructions.

Before uploading, manually test the staged folder: ROM picker, startup, rendering, controls, audio, an existing save, remembered-ROM behavior, and launching from the extracted folder on a later run. This source candidate's previous 37/37 non-gameplay CTest result is not interactive verification of the staged executable.

## User-supplied ROM and local developer builds

Players select a compatible ROM at runtime. Developers can generate and compile from source using `docs/BUILDING.md`; generated code and executables remain local. Neither artifact is included in the GitHub source tree.
