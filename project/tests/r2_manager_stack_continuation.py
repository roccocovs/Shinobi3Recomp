#!/usr/bin/env python3
"""Focused regression for Shinobi III's stack-selected Round 2 manager path."""

# Byte fixtures below construct synthetic test ROMs; no game ROM bytes are embedded.

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys
import uuid

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def put32(buf: bytearray, address: int, value: int) -> None:
    buf[address : address + 4] = value.to_bytes(4, "big")


def rom_image(reset_pc: int, blocks: list[tuple[int, bytes]]) -> bytes:
    image_size = max([0x2200] + [address + len(code) for address, code in blocks])
    image = bytearray(image_size)
    put32(image, 0, 0x00FFFFF0)
    put32(image, 4, reset_pc)
    image[0x100:0x10F] = b"SEGA GENESIS ".ljust(0x0F, b" ")
    image[0x120:0x150] = b"PEA CONTINUATION FIXTURE".ljust(0x30, b" ")
    image[0x150:0x180] = b"PEA CONTINUATION FIXTURE".ljust(0x30, b" ")
    image[0x1F0:0x1F3] = b"USA"
    for address, code in blocks:
        image[address : address + len(code)] = code
    return bytes(image)


def write_case(root: pathlib.Path, name: str, rom: bytes,
               extra_roots: tuple[int, ...]) -> tuple[pathlib.Path, pathlib.Path]:
    case = root / f"{name}-{uuid.uuid4().hex[:10]}"
    output = case / "generated"
    output.mkdir(parents=True)
    (case / "fixture.bin").write_bytes(rom)
    extras = ", ".join(f"0x{addr:06X}" for addr in extra_roots)
    (case / "game.toml").write_text(
        '[game]\noutput_prefix = "pea_fixture"\n'
        "[ram_layout]\n\n[functions]\n"
        f"extra = [{extras}]\n",
        encoding="utf-8",
    )
    return case, output


def run_generator(exe: pathlib.Path, case: pathlib.Path,
                  output: pathlib.Path) -> str:
    result = subprocess.run(
        [str(exe), str(case / "fixture.bin"), "--game",
         str(case / "game.toml"), "--output-dir", str(output)],
        text=True, capture_output=True, timeout=90, check=False,
    )
    log = result.stdout + result.stderr
    (case / "recompiler.log").write_text(log, encoding="utf-8")
    if result.returncode:
        raise AssertionError(f"fixture codegen failed; inspect {case}")
    return log


def generated_text(directory: pathlib.Path) -> str:
    parts = sorted(directory.glob("*_part*.c"))
    if not parts:
        raise AssertionError(f"no generated C parts in {directory}")
    return "\n".join(path.read_text(encoding="utf-8", errors="replace")
                     for path in parts)


def function_body(text: str, name: str) -> str:
    match = re.search(rf"\bvoid {re.escape(name)}\(void\)\s*\{{", text)
    if not match:
        raise AssertionError(f"generated function {name} is missing")
    opening = text.find("{", match.start())
    depth = 0
    for pos in range(opening, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : pos]
    raise AssertionError(f"generated function {name} has an unterminated body")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_branchful_pee_discovery(exe: pathlib.Path, work: pathlib.Path) -> None:
    # The PEA at $400 names $450. Its conditional paths converge at a static
    # tail jump to the independently known routine $500.
    branch_rom = rom_image(0x400, [
        (0x400, bytes.fromhex("48 7A 00 4E 4E 75")),
        (0x450, bytes.fromhex("66 04 60 02 4E 71 4E F9 00 00 05 00")),
        (0x500, bytes.fromhex("4E 75")),
    ])
    case, output = write_case(work, "branchful-continuation", branch_rom,
                              (0x500,))
    run_generator(exe, case, output)
    text = generated_text(output)
    dispatch = (output / "pea_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    body = function_body(text, "func_000450")
    require("func_000450" in dispatch,
            f"branchful PEA continuation did not become a dispatch entry; inspect {case}")
    require("/* $000450 */" in body and
            "/* $000452 */" in body and
            "/* $000456 */" in body and
            "goto label_000456;" in body and
            "recomp_tail_call(0x000500u); return;" in body,
            f"branchful continuation lost a conditional path or its terminal jump; inspect {case}")
    print("PASS bounded branchful PC-relative PEA continuation becomes a generated entry")

    # Shinobi III uses an absolute-long PEA for the state-11 continuation at
    # $02BBF8. Admit this addressing form only when the destination is a
    # bounded, valid branch-rich body that closes through RTS or a known code
    # target, just like the PC-relative form above.
    absolute_rom = rom_image(0x800, [
        (0x800, bytes.fromhex("48 79 00 00 08 50 4E 75")),
        (0x850, bytes.fromhex("66 04 60 02 4E 71 4E F9 00 00 09 00")),
        (0x900, bytes.fromhex("4E 75")),
    ])
    case, output = write_case(work, "absolute-long-branchful-continuation",
                              absolute_rom, (0x900,))
    run_generator(exe, case, output)
    text = generated_text(output)
    dispatch = (output / "pea_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    body = function_body(text, "func_000850")
    require("{ 0x000850u, func_000850 }" in dispatch and
            "/* $000850 */" in body and "/* $000856 */" in body and
            "recomp_tail_call(0x000900u); return;" in body,
            f"bounded absolute-long PEA continuation was not emitted intact; inspect {case}")
    print("PASS bounded branchful absolute-long PEA continuation becomes a generated entry")

    # A legal straight-line PEA data target is deliberately not admitted by
    # the new branchful rule; the existing short continuation heuristic stays
    # responsible for its prior behavior.
    data_rom = rom_image(0x600, [
        (0x600, bytes.fromhex("48 7A 00 1E 4E 75")),
        (0x620, bytes.fromhex("70 01 4E 75")),
    ])
    case, output = write_case(work, "straightline-pee-data", data_rom, ())
    run_generator(exe, case, output)
    dispatch = (output / "pea_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    require("{ 0x000620u, func_000620 }" not in dispatch,
            f"straight-line PEA data was promoted to a function entry; inspect {case}")
    print("PASS legal straight-line PEA data does not become a branchful function entry")

    absolute_data_rom = rom_image(0xA00, [
        (0xA00, bytes.fromhex("48 79 00 00 0A 20 4E 75")),
        (0xA20, bytes.fromhex("70 01 4E 75")),
    ])
    case, output = write_case(work, "absolute-long-pee-data", absolute_data_rom, ())
    run_generator(exe, case, output)
    dispatch = (output / "pea_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    require("{ 0x000A20u, func_000A20 }" not in dispatch,
            f"straight-line absolute PEA data was promoted to a function entry; inspect {case}")
    print("PASS straight-line absolute-long PEA data remains excluded")


def test_actual_shinobi_path(args: argparse.Namespace) -> None:
    rom_path = args.actual_rom.resolve()
    config_path = args.game_config.resolve()
    generated_dir = args.generated_dir.resolve()
    rom = rom_path.read_bytes()
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
            "unsupported ROM; use the validated Shinobi III revision")
    config = config_path.read_text(encoding="utf-8")

    # The ROM digest pins the tested revision. Native dispatch, stack,
    # continuation and generated-instruction assertions below verify behavior
    # without carrying literal game code or table bytes in this test.
    require("entry = 0x02BD3C" not in config and
            "0x02BD3C" not in config,
            "$02BD3C must be discovered from the PEA producer, not configured as an alias/root")

    parts = sorted(generated_dir.glob("*_part*.c"))
    require(parts, f"actual-ROM generated C is missing from {generated_dir}")
    text = generated_text(generated_dir)
    dispatch_path = generated_dir / "shinobi3_dispatch.c"
    dispatch = dispatch_path.read_text(encoding="utf-8", errors="replace")
    require(re.search(r"\{\s*0x02BD3Cu,\s*func_02BD3C\s*\}", dispatch),
            "actual ROM $02BD3C continuation is missing from generated dispatch")

    setup = function_body(text, "func_02B104")
    require("m68k_write32(g_cpu.A[7], 0x0002BD3Cu)" in setup and
            "m68k_write32(g_cpu.A[7], 0x0002BD12u)" in setup,
            "manager setup no longer pushes both verified continuation values")
    state3 = function_body(text, "func_02B4BC")
    require("g_cpu.A[7] += 4u" in state3 and
            "m68k_read32(g_cpu.A[7]) == 0x02BD3Cu" in state3 and
            "recomp_tail_call(0x02BD3Cu); return;" in state3,
            "state 3 does not discard $02BD12 then continue through $02BD3C")

    state4 = function_body(text, "func_02B51C")
    require("if ((g_cpu.SR & (1u<<3)))" in state4 and
            "goto label_02B52C;" in state4 and
            state4.find("goto label_02B52C;") < state4.find("/* $02B52A */") and
            "/* $02B532 */" in state4 and "g_cpu.A[7] += 4u" in state4 and
            "m68k_read32(g_cpu.A[7]) == 0x02BD12u" in state4 and
            "m68k_read32(g_cpu.A[7]) == 0x02BD3Cu" in state4 and
            "recomp_tail_call(0x02BD12u); return;" in state4 and
            "recomp_tail_call(0x02BD3Cu); return;" in state4,
            "state 4 lost its inactive $02BD12 or active $02BD3C route")
    for active_handler in ("func_02B53A", "func_02B564"):
        active_body = function_body(text, active_handler)
        require("g_split_sp_popped < 0 && m68k_read32(g_cpu.A[7]) == 0x02BD3Cu" in active_body and
                "recomp_tail_call(0x02BD3Cu); return;" in active_body,
                f"active state-4 handler {active_handler} cannot return through $02BD3C")

    continuation = function_body(text, "func_02BD3C")
    require("/* $02BD44 */" in continuation and
            "/* $02BD4E */" in continuation and
            "/* $02BDA8 */" in continuation and
            "/* $02BE20 */" in continuation and
            "/* $02BE80 */" in continuation,
            "$02BD3C does not contain the original conditional paths through the animation-map store")
    require(re.search(
        r"/\* \$02BE80 \*/\s*(?:g_r4_scroll_trace_current_pc = 0x[0-9A-F]{6}u;\s*)*m68k_write16\(\(uint32_t\)\(g_cpu\.A\[0\] \+ \(int32_t\)10\)",
        continuation),
        "generated $02BE80 mapping store is not a write to +$0A(A0)")
    for generated_fragment in (
        "g_cpu.A[1] = 0x0002BE92u;",
        "m68k_read16((uint32_t)(g_cpu.A[0] + (int32_t)4))",
        "m68k_read8((uint32_t)(g_cpu.A[0] + (int32_t)40))",
        "m68k_read8((uint32_t)(g_cpu.A[1] + m68k_brief_index_value(0x0001u, g_cpu.D[0], g_cpu.A[0]) + (1)))",
        "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)40)",
        "(uint16_t)0x256u",
    ):
        require(generated_fragment in continuation,
                f"generated initial animation-map logic is missing {generated_fragment}")

    # The manager constructor deliberately initializes mapping/cursor to zero.
    # States 3/4 then use the ROM's own sequence table. Check the dynamic
    # table offsets and valid advancing-entry shape; generated-code assertions
    # below verify that the live frame and cursor values drive the mapping.
    for state in (3, 4):
        offset = int.from_bytes(rom[0x02BE92 + state * 2 : 0x02BE92 + state * 2 + 2], "big")
        require(offset < len(rom) - 0x02BE92 - 2,
                f"state {state} animation sequence offset is outside the ROM")
        sequence = rom[0x02BE92 + offset : 0x02BE92 + offset + 20]
        frame_step, frame_index = sequence[0], sequence[1]
        require(frame_step > 0 and frame_step % 2 == 0 and frame_index != 0xFF,
                f"state {state} sequence does not begin with a valid advancing frame")
    require("func_02BD3C" in dispatch and "0x0268u" not in continuation,
            "continuation dispatch missing or a hardcoded mapping was introduced")
    print("PASS actual Shinobi ROM: both stack routes reach $02BD3C and authentic $02BE20/$02BE80 logic is generated")

    # State 11 pushes $02BC3A before its computed jump. The selected worker's
    # RTS must consume that exact stack word and tail-dispatch to the helper;
    # the helper then returns through the outer manager continuation.
    require(re.search(r"\{\s*0x02BC3Au,\s*func_02BC3A\s*\}", dispatch),
            "state-11 stack-selected continuation $02BC3A is missing from dispatch")
    for returning_handler in ("func_02BC08", "func_02BC22", "func_02BC2C"):
        handler = function_body(text, returning_handler)
        require("g_split_sp_popped < 0 && m68k_read32(g_cpu.A[7]) == 0x02BC3Au" in handler and
                "recomp_tail_call(0x02BC3Au); return;" in handler,
                f"{returning_handler} does not return through its pushed $02BC3A continuation")
    state11_continuation = function_body(text, "func_02BC3A")
    state11_substate3 = function_body(text, "func_02BC5E")
    require("/* $02BC3A */" in state11_continuation and
            "/* $02BC3E */" in state11_continuation and
            "if ((g_cpu.SR & (1u<<3)))" in state11_continuation and
            "goto label_02BC4C;" in state11_continuation and
            "/* $02BC4C */" in state11_continuation and
            "/* $02BC50 */" in state11_continuation and
            "recomp_tail_call(0x02BC5Eu); return;" in state11_continuation and
            "m68k_write8((uint32_t)(g_cpu.A[0] + (int32_t)40), (uint8_t)(0x03u))" in state11_substate3 and
            "recomp_tail_call(0x02BD3Cu); return;" in state11_substate3,
            "state-11 continuation lost its authentic spawn checks, substate-3 update, or outer return")
    # The generated updater reads the ROM sequence and contains the cursor
    # update/termination control flow; no extracted sequence bytes are bundled.
    require("m68k_read8((uint32_t)(g_cpu.A[1] +" in continuation and
            "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)40)" in continuation,
            "state-11 sequence updater no longer reads and advances its live ROM cursor")
    require("/* $02BE50 */" in continuation and
            "_02BE50r = (uint16_t)((uint16_t)(_t02BE50) + (uint16_t)g_cpu.D[1])" in continuation and
            "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)40), (uint16_t)(_02BE50r))" in continuation,
            "shared animation continuation no longer applies the state's cursor step to +$28")
    print("PASS actual Shinobi state-11 PEA continuation reaches spawn/transition code and outer animation updater")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recompiler", required=True, type=pathlib.Path)
    parser.add_argument("--work-dir", required=True, type=pathlib.Path)
    parser.add_argument("--actual-rom", required=True, type=pathlib.Path)
    parser.add_argument("--game-config", required=True, type=pathlib.Path)
    parser.add_argument("--generated-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()
    exe = args.recompiler.resolve()
    work = args.work_dir.resolve()
    require(exe.is_file(), f"recompiler executable not found: {exe}")
    work.mkdir(parents=True, exist_ok=True)
    test_branchful_pee_discovery(exe, work)
    test_actual_shinobi_path(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
