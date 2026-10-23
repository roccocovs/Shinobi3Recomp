# Cleanup manifest

This manifest describes cleanup within this isolated candidate only. Historical candidate and build directories, saves, captures, and accepted executables elsewhere were not modified.

## Removed from this candidate

- `project/game/shinobi3.gen`: confirmed SHA-256 matched the supported original ROM; the user must supply the build/play input.
- `engine/runner/external/SDL2-VC.zip`: redundant archive; the extracted SDL2 2.28.5 SDK and its license remain.
- `project/tools/diagnostic-deps/`: bundled Capstone/Pillow runtime and bytecode caches were unnecessary to build or run the game. The optional disassembler now imports installed Capstone and declares the pinned version in `requirements-tools.txt`.
- `project/tools/archive/Capture-Sound-Event-retired-20261010.ps1`: retired diagnostic utility.
- `project/run-test-build.ps1`: obsolete harness forced floor settings and referenced an old package-local ROM; replaced by the parameterized release build script.
- `project/tests/boss1-fight-approach.input`: unused by CMake and contained machine-local evidence paths.
- Python `__pycache__` folders.
- `project/tools/recreate-engine.py` and its manifests: legacy scripts that reconstructed a different local engine checkout and referenced old workspace paths; this candidate vendors its build engine directly.

## Retained or relocated

- The complete engine, generator, tests, game configuration, and vendored dependency sources/licenses remain because they are needed to build or maintain the project.
- Historical round notes, test logs, ROM disassemblies, and reverse-engineering notes were not copied into this candidate. Preserve those separate archives locally as desired; they are not build inputs.
- `SDL2-2.28.5` headers, CMake package files, import libraries, and `SDL2.dll` remain for build/package reproducibility; only `SDL2.dll` is copied beside the final executable.
- Regression fixtures and scripts remain, including gameplay-launching fixtures. The release test script inspects the live CTest list and excludes gameplay tests.

## Changes for the public-source candidate

- Excluded `engine/external/m68k-recomp-core/profiles/genesis/code_generator.c.pea-before`, an unused historical backup. The accepted generator source is unchanged.
- Rewrote actual-ROM test checks that embedded short instruction/data byte strings. The tests continue to validate the supported ROM SHA-256 and now decode instruction classes and dynamic branch/table destinations, inspect generated native dispatch and bodies, and verify stack/return behavior. Generic recompiler tests keep byte fixtures only when they construct synthetic ROM images themselves.
- Added the required `rbengine` MIT attribution and pointed to its unchanged full license file.
- No runtime/gameplay implementation was changed by this cleanup.

## Excluded from the candidate source tree

The original ROM, generated translated game sources, build output, save files, diagnostic captures, private analysis, and historical source/build directories are excluded. The candidate does contain SDL2 SDK files for local compilation; their attribution is retained and redistribution remains subject to license review. This is not a rights clearance or an end-user game package.


## Regression changes and retained invariants

The test registration is unchanged: 37 non-gameplay tests remain, and the nine gameplay-launching tests remain registered but excluded by `test-non-gameplay.ps1`.

- `project/tests/check-a7-byte-stack.py` no longer carries four expected opcode words. It pins the accepted ROM by SHA-256 and checks the generated `$006E74` stack read and exact two-byte stack increment, including the calculated loop stack effect.
- `project/tests/check-sound-selector-fallback.py` replaces copied instruction spans and an enumerated pointer-value table with SHA-256 validation, the eight-entry table's alignment/uniqueness/in-ROM structure, decoded BEQ target, and code-generator/generated-code checks for the selector fallback.
- `project/tests/check-native-table-coverage.py` uses the supported SHA-256 and decodes the indexed jump and branch classes/targets as words; it still verifies configured roots and generated dispatch.
- `project/tests/r2_manager_stack_continuation.py` keeps its synthetic fixture ROMs, but removes copied live-ROM manager and animation byte sequences. The live checks now validate supported ROM identity, table offsets and entry shape, generated mapping/cursor operations, manager continuation addresses, and exact stack-slot return behavior.
- `project/tests/r7-ending-z80-handshake.py` removes copied bus-handshake instruction spans. It validates ROM identity and checks the generated guest handshake loop, the runtime BUSREQ/mailbox-release scheduling edge, rollback state, and a bounded scheduler counterexample.
- `project/tests/r7-ending-progression.py` checks each ending BRA.W instruction class and computes its signed destination from the supplied ROM. It retains generated entry coverage and executes the isolated ending-fragment fixture.
- `project/tests/r7-final-boss-execution.py` validates the selected callback table word as a decoded address and checks each animation branch opcode and computed destination; generated callback, scene, actor-state and return-path assertions remain.
- `project/tests/r4-manager-state18-scroll-continuation.py` decodes the three computed-table BRA.S rows by opcode class and signed displacement, and keeps PEA target, manager state rows, generated dispatch, exact stack guards, and cursor-update checks.
- `project/tests/r4-boss-state30-complete-dispatch.py`, `r4-manager-state34-efc0-dispatch.py`, `r4-selector43-component-dispatch.py`, and `r7-act0-callbacks.py` use instruction-class decoding plus dynamic branch destinations for state rows/zone veneers; the state-domain, native-dispatch, generated operation, and return semantics checks remain.
- The other ROM-backed callback and boss regressions under `project/tests/` were changed from literal instruction-prefix comparisons to the same supported-ROM digest plus table selection, decoded target, generated-dispatch/body, and stack/continuation checks. This includes R3 stage 2; R4 Act 1, boss phase/final-boss and manager continuations; R5 callbacks/camera; R6 Act 0/Act 1, Karura return and Ninja Master camera; and R7 Act 0/Act 1/final-boss paths.
- `project/tests/interior_alias_codegen.py` retains its byte strings only in explicitly synthetic generic-recompiler fixture ROMs. Its actual-ROM case uses the supported image hash and verifies shared-body aliases, computed target labels, the exact generated continuation, and that unresolved targets were not promoted.

No test was removed or unregistered. The old exact-byte assertions are not claimed to be byte-for-byte coverage; their ROM identity and intended control-flow/dispatch/stack invariants remain covered semantically. The audited test suite passed 37/37 after these changes.


The ROM-backed callback regression scripts covered by the grouped explanation above are `r3-stage2-callback-dispatch.py`; `r4-act1-callback-dispatch.py`, `r4-boss-phase-dispatch.py`, `r4-boss-state30-complete-dispatch.py`, `r4-final-boss-dispatch.py`, `r4-manager-pea-return.py`, `r4-manager-state18-scroll-continuation.py`, `r4-manager-state2c-dispatch.py`, `r4-manager-state34-efc0-dispatch.py`, `r4-manager-state84-scroll-dispatch.py`, and `r4-selector43-component-dispatch.py`; `r5-camera-scroll-callbacks.py` and `r5-stage-callback-roots.py`; `r6-act0-scene-callbacks.py`, `r6-act1-background-callbacks.py`, `r6-actor62-rtr-local-continuation.py`, and `r6-ninja-master-camera-callback.py`; plus `r7-act0-callbacks.py`, `r7-act1-foreground-callbacks.py`, `r7-final-boss-execution.py`, and `r7-ending-progression.py`. The checks they replaced were literal instruction windows; the replacements validate the same registered targets and control-flow relationships through ROM decoding and generated native ownership/body assertions. The other runtime/diagnostic tests were not removed from CTest; any textual-only changes there are documentation or line-ending normalization.
