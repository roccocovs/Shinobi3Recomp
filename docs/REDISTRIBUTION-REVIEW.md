# Redistribution and licensing review

This records the project's technical distribution model and license boundaries. It is not legal advice or a guarantee of clearance.

## Artifacts

- **GitHub source repository:** Includes the recompiler/runtime source, audited ROM-specific technical metadata, build/test tools, and notices. It excludes the original ROM, generated Shinobi C translations, compiled game executable, extracted Sega graphics/audio, and personal saves.
- **Windows GitHub Release:** A separate precompiled application is planned. The executable includes statically translated 68000 instructions generated from Shinobi III's ROM, plus project runtime and third-party components. It does not include the ROM image; users must select a compatible ROM at runtime for game data and behavior. Requiring users to provide the ROM does not make the executable ROM-independent or remove its ROM-derived code.
- **Developer local build:** Generates translated C and the executable locally from the user's ROM. Those outputs remain outside the source repository.

The author has authorized publication of the audited technical configuration including addresses, selectors, aliases, and callbacks. The audit found those files primarily contain functional metadata and integration rather than copied instruction streams or assets. The executable distribution is a different artifact and expressly contains generated instruction translations.

## Licensing scope

Top-level `LICENSE.md` offers PolyForm Noncommercial 1.0.0 for roccocovs's original contributions to the extent of that authorship. Matthew Stan retains copyright and licensing for the Genesis Recompiler framework under its included PolyForm terms. Third-party dependencies retain their own licenses. No project license relicenses Sega's game, ROM code, marks, or audiovisual content. Preserve the notices and license texts accompanying both source and binary distributions.

## Practical publication steps

Keep the Git repository source-only. Upload the Windows folder as a separate GitHub Release asset after manual review and gameplay verification of that exact staged executable. Include its README, SDL2 runtime DLL, and the applicable license/notice files. Do not add the ROM, generated game C, PDB, diagnostics, saves, or development outputs. See `PUBLISHING.md` for an allowlist and manual checks.

No Sega permission or endorsement is claimed. The user's distribution decision and the included software licenses do not establish rights in Sega material.
