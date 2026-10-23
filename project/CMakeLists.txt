cmake_minimum_required(VERSION 3.24)
project(Shinobi3Recomp VERSION 0.1.0 LANGUAGES C CXX)

# The portable Zig toolchain does not expose a separate ar/ranlib on PATH.
# Supply its tiny wrappers when this reconstructed project is built beside
# the restored local tool bundle; normal installed toolchains keep their own.
if(WIN32)
    set(_local_tools "${CMAKE_CURRENT_SOURCE_DIR}/../tools")
    if(EXISTS "${_local_tools}/zig-ar.cmd")
        set(CMAKE_AR "${_local_tools}/zig-ar.cmd")
        set(CMAKE_RANLIB "${_local_tools}/zig-ranlib.cmd")
    endif()
endif()

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(GENESIS_RECOMP_ROOT "" CACHE PATH "Path to the vendored GenesisRecomp source")
if(NOT GENESIS_RECOMP_ROOT)
    message(FATAL_ERROR "Set GENESIS_RECOMP_ROOT to the repository's engine directory")
endif()
get_filename_component(RECOMP_ROOT "${GENESIS_RECOMP_ROOT}" ABSOLUTE)
set(RUNNER_ROOT "${RECOMP_ROOT}/runner")

set(SHINOBI_ROM_PATH "" CACHE FILEPATH "Path to a legally obtained compatible Shinobi III ROM")
if(NOT SHINOBI_ROM_PATH OR NOT EXISTS "${SHINOBI_ROM_PATH}")
    message(FATAL_ERROR "Set SHINOBI_ROM_PATH to your compatible 1 MiB US Shinobi III ROM; ROMs are not included")
endif()

set(SHINOBI_ZIG_EXE "" CACHE FILEPATH "Optional absolute path to the Zig compiler used by the wrapper scripts")
file(SIZE "${SHINOBI_ROM_PATH}" _shinobi_rom_size)
if(NOT _shinobi_rom_size EQUAL 1048576)
    message(FATAL_ERROR "SHINOBI_ROM_PATH must be exactly 1,048,576 bytes (got ${_shinobi_rom_size})")
endif()
file(SHA256 "${SHINOBI_ROM_PATH}" _shinobi_rom_sha256)
if(NOT _shinobi_rom_sha256 STREQUAL "e0c50ed80fa1b75325344c2260a26841936d077e2ae1689c2522e3cc484739e3")
    message(FATAL_ERROR "SHINOBI_ROM_PATH does not match the documented compatible ROM (SHA-256 mismatch)")
endif()

option(SHINOBI_ENABLE_DEV_DIAGNOSTICS "Compile opt-in Round 4 and ending recorders" OFF)

option(SHINOBI_ENABLE_TRACE "Build the development command server and frame trace" OFF)
option(SHINOBI_ENABLE_COSIM "Build the native/interpreter lockstep diagnostic runner" OFF)
option(SHINOBI_ENABLE_REVERSE_DEBUG "Record native block and WRAM-write history" OFF)
if(SHINOBI_ENABLE_REVERSE_DEBUG AND NOT SHINOBI_ENABLE_TRACE)
    message(FATAL_ERROR "SHINOBI_ENABLE_REVERSE_DEBUG requires SHINOBI_ENABLE_TRACE")
endif()

if(WIN32)
    list(APPEND CMAKE_PREFIX_PATH "${RUNNER_ROOT}/external/SDL2/SDL2-2.28.5/cmake")
endif()
find_package(SDL2 REQUIRED)

# GenesisRecompGenerated.cmake uses RECOMP_ROOT to locate the native
# recompiler target. Keep that engine path explicit in this consumer build.
set(RECOMP_ROOT "${GENESIS_RECOMP_ROOT}")
include("${RECOMP_ROOT}/cmake/GenesisRecompGenerated.cmake")
genesisrecomp_add_generated_sources(
    SHINOBI_GENERATED_SOURCES
    shinobi3
    "${CMAKE_SOURCE_DIR}/game"
    "${SHINOBI_ROM_PATH}"
    REVERSE_DEBUG ${SHINOBI_ENABLE_REVERSE_DEBUG})

if(SHINOBI_ENABLE_TRACE OR SHINOBI_ENABLE_COSIM)
    set(_trace ON)
else()
    set(_trace OFF)
endif()
genesisrecomp_runner_sources(SHINOBI_RUNNER_SOURCES
    TRACE ${_trace}
    REVERSE_DEBUG ${SHINOBI_ENABLE_REVERSE_DEBUG})

if(SHINOBI_ENABLE_DEV_DIAGNOSTICS)
    list(APPEND SHINOBI_RUNNER_SOURCES
        "${RUNNER_ROOT}/r4_scroll_trace.c"
        "${RUNNER_ROOT}/r7_ending_diag.c")
else()
    # The normal release has no disk recorder or 32K-event diagnostic ring.
    # These stubs retain the generated/interpreter ABI and current-PC value
    # without adding any guest-visible changes.
    list(APPEND SHINOBI_RUNNER_SOURCES
        "${RUNNER_ROOT}/shinobi_release_diagnostic_stubs.c")
endif()

if(SHINOBI_ENABLE_COSIM)
    list(APPEND SHINOBI_RUNNER_SOURCES
        "${RUNNER_ROOT}/cosim.c"
        "${RUNNER_ROOT}/cosim_visible.c"
        "${RUNNER_ROOT}/cosim_cycles.c"
        "${RUNNER_ROOT}/game_cycles.c")
    list(APPEND SHINOBI_GENERATED_SOURCES "${SHINOBI_GENERATED_SOURCES_CYCLES}")
endif()

add_executable(Shinobi3Recomp WIN32
    ${SHINOBI_RUNNER_SOURCES}
    ${SHINOBI_GENERATED_SOURCES}
    game/shinobi3_spec.c
    "${RUNNER_ROOT}/rom_selection.c"
    "${RUNNER_ROOT}/rom_sha256.c")
add_dependencies(Shinobi3Recomp ${SHINOBI_GENERATED_SOURCES_TARGET})
set_target_properties(Shinobi3Recomp PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/package")
target_include_directories(Shinobi3Recomp PRIVATE
    "${RUNNER_ROOT}"
    "${RUNNER_ROOT}/include"
    "${RUNNER_ROOT}/external/ymfm/src"
    "${RUNNER_ROOT}/external/superzazu"
    "${RUNNER_ROOT}/external/clowncommon"
    "${RUNNER_ROOT}/video"
    "${RECOMP_ROOT}/recompiler/src"
    "${CMAKE_CURRENT_SOURCE_DIR}/game")
target_compile_definitions(Shinobi3Recomp PRIVATE
    INCLUDE_GENERATED_CODE=1
    ENABLE_RECOMPILED_CODE=1
    OWN_BACKEND=1
    DEFAULT_DEBUG_PORT=4382
    GENESIS_GAME_VERSION="${PROJECT_VERSION}")
if(NOT SHINOBI_ENABLE_DEV_DIAGNOSTICS)
    target_compile_definitions(Shinobi3Recomp PRIVATE SHINOBI_RELEASE_BUILD=1)
endif()
if(SHINOBI_ENABLE_REVERSE_DEBUG)
    target_compile_definitions(Shinobi3Recomp PRIVATE SONIC_REVERSE_DEBUG=1)
endif()
if(SHINOBI_ENABLE_COSIM)
    target_compile_definitions(Shinobi3Recomp PRIVATE GENESIS_COSIM=1)
endif()
if(CMAKE_C_COMPILER_ID MATCHES "Clang")
    # Zig's bundled Clang promotes the runner's build-stamp date macros to
    # errors unless this warning is explicitly non-fatal.
    target_compile_options(Shinobi3Recomp PRIVATE -Wno-error=date-time)
endif()
target_link_libraries(Shinobi3Recomp PRIVATE SDL2::SDL2main SDL2::SDL2)
if(WIN32)
    target_link_libraries(Shinobi3Recomp PRIVATE bcrypt)
endif()

add_executable(ShinobiControllerProfileTest
    tests/controller-profile.c
    game/shinobi3_spec.c)
target_include_directories(ShinobiControllerProfileTest PRIVATE
    "${RUNNER_ROOT}"
    "${RUNNER_ROOT}/include"
    "${RUNNER_ROOT}/external/clowncommon"
    "${CMAKE_CURRENT_SOURCE_DIR}/game")
target_link_libraries(ShinobiControllerProfileTest PRIVATE SDL2::SDL2)

add_executable(ShinobiRomSelectionTest
    tests/rom-selection-test.c
    "${RUNNER_ROOT}/rom_selection.c")
target_include_directories(ShinobiRomSelectionTest PRIVATE "${RUNNER_ROOT}")

add_executable(ShinobiRomSha256Test
    tests/rom-sha256-test.c
    "${RUNNER_ROOT}/rom_sha256.c")
target_include_directories(ShinobiRomSha256Test PRIVATE "${RUNNER_ROOT}")
target_link_libraries(ShinobiRomSha256Test PRIVATE bcrypt)

add_executable(ShinobiSixButtonScriptTest
    tests/sixbutton-input.c
    "${RUNNER_ROOT}/input_script.c")
target_include_directories(ShinobiSixButtonScriptTest PRIVATE
    "${RUNNER_ROOT}"
    "${RUNNER_ROOT}/include")

add_executable(ShinobiRomRead32Test
    tests/rom-read32.c
    "${RECOMP_ROOT}/recompiler/src/rom_parser.c")
target_include_directories(ShinobiRomRead32Test PRIVATE
    "${RECOMP_ROOT}/recompiler/src")

add_executable(R3GraphicsDiagCaptureHarness
    tests/r3-graphics-diag-harness.c)
target_include_directories(R3GraphicsDiagCaptureHarness PRIVATE
    "${RUNNER_ROOT}"
    "${RUNNER_ROOT}/include"
    "${RUNNER_ROOT}/video"
    "${RUNNER_ROOT}/external/superzazu"
    "${RUNNER_ROOT}/external/ymfm/src"
    "${RUNNER_ROOT}/external/clowncommon")

add_executable(R4ScrollProvenanceHarness
    tests/r4-scroll-provenance-harness.c
    "${RUNNER_ROOT}/r4_scroll_trace.c")
target_include_directories(R4ScrollProvenanceHarness PRIVATE
    "${RUNNER_ROOT}/include")
target_compile_definitions(R4ScrollProvenanceHarness PRIVATE
    R4_SCROLL_TRACE_TESTING=1)

add_executable(R7EndingLiveDiagHarness
    tests/r7-ending-live-diag-harness.c
    "${CMAKE_CURRENT_SOURCE_DIR}/../engine/runner/r7_ending_diag.c")
target_include_directories(R7EndingLiveDiagHarness PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/../engine/runner")

add_executable(ShinobiStateStoreTest
    tests/state-store-test.c
    "${RUNNER_ROOT}/state_store.c"
    "${RUNNER_ROOT}/state_container.c"
    "${RUNNER_ROOT}/state_slots.c")
target_include_directories(ShinobiStateStoreTest PRIVATE "${RUNNER_ROOT}")

if(WIN32)
    target_link_libraries(Shinobi3Recomp PRIVATE ws2_32 comdlg32)
    # CMake's WIN32 executable normally maps to -mwindows. Keep an explicit
    # PE subsystem directive as well because the Zig/Clang driver otherwise
    # produced a console-subsystem image in the tested MinGW configuration.
    target_link_options(Shinobi3Recomp PRIVATE "LINKER:--subsystem,windows")
    add_custom_command(TARGET Shinobi3Recomp POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${RUNNER_ROOT}/external/SDL2/SDL2-2.28.5/lib/x64/SDL2.dll"
            "$<TARGET_FILE_DIR:Shinobi3Recomp>"
        )
    if(SHINOBI_ENABLE_TRACE AND SHINOBI_ENABLE_REVERSE_DEBUG)
        add_custom_command(TARGET Shinobi3Recomp POST_BUILD
            COMMAND "${CMAKE_COMMAND}" -E copy_if_different
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/Capture-Sound-Evidence.ps1"
                "$<TARGET_FILE_DIR:Shinobi3Recomp>/Capture-Sound-Evidence.ps1"
            COMMAND "${CMAKE_COMMAND}" -E copy_if_different
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/sound-trace-debug.ini"
                "$<TARGET_FILE_DIR:Shinobi3Recomp>/debug.ini")
    endif()
endif()
genesisrecomp_runner_target(Shinobi3Recomp)

find_package(Python3 COMPONENTS Interpreter REQUIRED)
enable_testing()
add_test(NAME ShinobiRomSelection
    COMMAND ShinobiRomSelectionTest)
add_test(NAME ShinobiControllerProfile
    COMMAND ShinobiControllerProfileTest)
add_test(NAME ShinobiRomSha256
    COMMAND ShinobiRomSha256Test "${SHINOBI_ROM_PATH}")
add_test(NAME ShinobiReleaseDefaults
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/release-defaults.py"
        --spec "${CMAKE_CURRENT_SOURCE_DIR}/game/shinobi3_spec.c"
        --glue "${RUNNER_ROOT}/glue.c"
        --controller-test "${CMAKE_CURRENT_SOURCE_DIR}/tests/controller-profile.c"
        --main "${RUNNER_ROOT}/main.c"
        --change-rom-helper "${CMAKE_CURRENT_SOURCE_DIR}/../Change-ROM.vbs")
add_test(NAME ShinobiReleasePackageSmoke
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/release-package-smoke.py"
        --exe "$<TARGET_FILE:Shinobi3Recomp>"
        --package "$<TARGET_FILE_DIR:Shinobi3Recomp>")
add_test(NAME R4ScrollProvenanceSynthetic
    COMMAND R4ScrollProvenanceHarness)
add_test(NAME R4ScrollProvenanceGeneratedHooks
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-scroll-provenance-codegen.py"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME GenesisInteriorAliasCodegen
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/interior_alias_codegen.py"
        --recompiler "$<TARGET_FILE:GenesisRecomp>"
        --work-dir "${CMAKE_CURRENT_BINARY_DIR}/interior-alias-regression"
        --actual-rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml")
add_test(NAME Round2ManagerStackContinuation
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r2_manager_stack_continuation.py"
        --recompiler "$<TARGET_FILE:GenesisRecomp>"
        --work-dir "${CMAKE_CURRENT_BINARY_DIR}/r2-manager-stack-continuation"
        --actual-rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME ShinobiSixButtonScript
    COMMAND ShinobiSixButtonScriptTest
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/sixbutton-input.input")
add_test(NAME ShinobiRomRead32
    COMMAND ShinobiRomRead32Test)
add_test(NAME R3GraphicsDiagCapture
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r3-graphics-diag-capture.py"
        --harness "$<TARGET_FILE:R3GraphicsDiagCaptureHarness>")
add_test(NAME R3Stage2CallbackDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r3-stage2-callback-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4Act1CallbackDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-act1-callback-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4FinalBossDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-final-boss-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4ManagerPeaReturn
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-manager-pea-return.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4ManagerState2CDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-manager-state2c-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4BossPhaseDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-boss-phase-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4BossState30CompleteDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-boss-state30-complete-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4ManagerState34Efc0Dispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-manager-state34-efc0-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4ManagerState84ScrollDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-manager-state84-scroll-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R4ManagerState18ScrollContinuation
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-manager-state18-scroll-continuation.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R5StageCallbackRoots
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r5-stage-callback-roots.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R5CameraScrollCallbacks
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r5-camera-scroll-callbacks.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R6Act0SceneCallbacks
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r6-act0-scene-callbacks.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R6Act1BackgroundCallbacks
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r6-act1-background-callbacks.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R6NinjaMasterCameraCallback
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r6-ninja-master-camera-callback.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R6Actor62RtrLocalContinuation
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r6-actor62-rtr-local-continuation.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R7Act0Callbacks
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r7-act0-callbacks.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R7Act1ForegroundCallbacks
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r7-act1-foreground-callbacks.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R7FinalBossExecution
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r7-final-boss-execution.py"
        --rom "${SHINOBI_ROM_PATH}"
        --game-config "${CMAKE_CURRENT_SOURCE_DIR}/game/game.toml"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME R7EndingProgression
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r7-ending-progression.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3"
        --runtime-include "${RUNNER_ROOT}/include"
        --cc "${CMAKE_C_COMPILER}"
        --work-dir "${CMAKE_CURRENT_BINARY_DIR}/ending-progression-fixture")
if(SHINOBI_ZIG_EXE)
    set(_ending_progression_env
        "ZIG_EXE=${SHINOBI_ZIG_EXE}"
        "ZIG_LOCAL_CACHE_DIR=${CMAKE_CURRENT_BINARY_DIR}/zig-cache/local"
        "ZIG_GLOBAL_CACHE_DIR=${CMAKE_CURRENT_BINARY_DIR}/zig-cache/global")
    set_tests_properties(R7EndingProgression PROPERTIES ENVIRONMENT "${_ending_progression_env}")
endif()
add_test(NAME R7EndingLiveDiagBounded
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r7-ending-live-diag.py"
        --harness "$<TARGET_FILE:R7EndingLiveDiagHarness>"
        --work-dir "${CMAKE_CURRENT_BINARY_DIR}/ending-live-diag-fixture"
        --glue "${RUNNER_ROOT}/glue.c")
add_test(NAME R7EndingZ80Handshake
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r7-ending-z80-handshake.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3/shinobi3_part31.c"
        --glue "${RUNNER_ROOT}/glue.c")
add_test(NAME R4Selector43ComponentDispatch
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r4-selector43-component-dispatch.py"
        --rom "${SHINOBI_ROM_PATH}"
        --generated-dir "${CMAKE_CURRENT_BINARY_DIR}/generated/shinobi3")
add_test(NAME ShinobiStateStore
    COMMAND ShinobiStateStoreTest)
add_test(NAME ShinobiStateInputWiring
    COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/r3-save-state-wiring.py"
        --engine "${RUNNER_ROOT}"
        --game-spec "${CMAKE_CURRENT_SOURCE_DIR}/game/shinobi3_spec.c"
        --main "${RUNNER_ROOT}/main.c")

if(WIN32)
    find_program(POWERSHELL_EXECUTABLE powershell REQUIRED)
    function(add_shinobi_gameplay_test NAME INPUT_SCRIPT FLOOR SIX_BUTTON_PROFILE)
        add_test(NAME ${NAME}
            COMMAND "${POWERSHELL_EXECUTABLE}" -NoProfile -ExecutionPolicy Bypass
                -File "${CMAKE_CURRENT_SOURCE_DIR}/tests/run-gameplay-regression.ps1"
                -Exe "$<TARGET_FILE:Shinobi3Recomp>"
                -Rom "${SHINOBI_ROM_PATH}"
                -InputScript "${CMAKE_CURRENT_SOURCE_DIR}/tests/${INPUT_SCRIPT}"
                -Floor "${FLOOR}"
                -SixButtonProfile "${SIX_BUTTON_PROFILE}")
        set_tests_properties(${NAME} PROPERTIES TIMEOUT 90 LABELS "gameplay;launches-game")
    endfunction()

    add_shinobi_gameplay_test(ShinobiRunGrounded3Button run-grounded.input 1 0)
    add_shinobi_gameplay_test(ShinobiRunShurikenJitsuGrounded6Button startup-actions.input 1 1)
    add_shinobi_gameplay_test(ShinobiRunShurikenJitsuGroundedFloor0 startup-actions.input 0 1)
    add_shinobi_gameplay_test(ShinobiExpertZeroJumpMeleeGroundedFloor1 expert-zero-jump-melee.input 1 1)
    add_shinobi_gameplay_test(ShinobiExpertZeroJumpMeleeGroundedFloor0 expert-zero-jump-melee.input 0 1)
endif()
if(WIN32)
    add_shinobi_gameplay_test(ShinobiDuckShurikenGroundedFloor0 duck-shuriken.input 0 1)
    add_shinobi_gameplay_test(ShinobiDuckShurikenGroundedFloor1 duck-shuriken.input 1 1)
endif()

if(WIN32)
    add_shinobi_gameplay_test(ShinobiDoubleJumpShurikenBurstYFloor0 doublejump-shuriken-burst-y.input 0 1)
    add_shinobi_gameplay_test(ShinobiDoubleJumpShurikenBurstBFloor0 doublejump-shuriken-burst-b.input 0 1)
endif()


