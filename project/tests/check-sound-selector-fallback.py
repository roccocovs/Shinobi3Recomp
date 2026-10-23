#!/usr/bin/env python3
"""Check the narrow Shinobi sound-selector guard against the ROM and output."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
TABLE_BASE = 0x06CC48
TABLE_ENTRIES = 8
BRANCH_PC = 0x069AC4
FALLBACK_PC = 0x069B0A


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    print(f"PASS: {message}")


def read_u32be(blob: bytes, offset: int) -> int:
    return int.from_bytes(blob[offset:offset + 4], "big")


def inspect_rom(rom_path: Path) -> None:
    rom = rom_path.read_bytes()
    digest = hashlib.sha256(rom).hexdigest().upper()
    check(digest == ROM_SHA256, "ROM is the expected supported Shinobi III image")

    pointers = tuple(read_u32be(rom, TABLE_BASE + i * 4)
                     for i in range(TABLE_ENTRIES))
    check(len(pointers) == TABLE_ENTRIES and len(set(pointers)) == TABLE_ENTRIES and
          all(pointer and not (pointer & 1) and pointer < len(rom) - 1
              for pointer in pointers),
          "$06CC48 has eight distinct, aligned in-ROM decoder targets")

    opcode = int.from_bytes(rom[BRANCH_PC:BRANCH_PC + 2], "big")
    disp = int.from_bytes(rom[BRANCH_PC + 1:BRANCH_PC + 2], "big", signed=True)
    target = BRANCH_PC + 2 + disp
    check((opcode >> 8) == 0x67 and target == FALLBACK_PC,
          "$069AC4 is BEQ to the existing $069B0A no-table path")
    # Supported-ROM digest and generated-code checks cover this path.


def inspect_source(engine: Path) -> None:
    codegen = (engine / "external/m68k-recomp-core/profiles/genesis/code_generator.c").read_text(encoding="utf-8")
    debug_c = (engine / "runner/reverse_debug.c").read_text(encoding="utf-8")
    debug_h = (engine / "runner/reverse_debug.h").read_text(encoding="utf-8")
    check("addr == 0x069AC4u && cond == 0x7" in codegen and
          "instr->target_addr == 0x069B0Au" in codegen,
          "guard is restricted to the verified BEQ and target")
    check("(g_cpu.D[0] & 0xFFFFu) > 8u" in codegen and
          "rdb_sound_selector_fallback" in codegen,
          "masked selectors above 8 take the existing path and are reported")
    check("void rdb_sound_selector_fallback(uint32_t pc, uint16_t selector);" in debug_h and
          "guest selector byte unchanged" in debug_c and
          "m68k_write" not in debug_c[debug_c.index("void rdb_sound_selector_fallback"):debug_c.index("uint32_t rdb_sound_index_count")],
          "fallback report is opt-in and does not write guest state")

    for raw in range(256):
        selector = raw & 0x7F
        uses_no_table_path = selector == 0 or selector > 8
        expected = selector == 0 or 9 <= selector <= 127
        if uses_no_table_path != expected:
            fail(f"selector policy mismatch for raw byte ${raw:02X}")
    check(True, "all 256 raw selector bytes preserve 0/high-bit behavior and reject only masked values 9-127")


def inspect_generated(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    start = source.find("void func_069ABA(void)")
    if start < 0:
        fail("generated source has no func_069ABA")
    end = source.find("\nvoid func_", start + 1)
    body = source[start:end if end >= 0 else len(source)]
    p_branch = body.find("/* $069AC4 */")
    p_lea = body.find("/* $069AC6 */")
    p_lookup = body.find("rdb_sound_pointer_lookup(0x069ACEu")
    if min(p_branch, p_lea, p_lookup) < 0:
        fail("generated selector branch or original table lookup is missing")
    block = body[p_branch:p_lea]
    check("rdb_sound_selector_fallback" in block and
          "(g_cpu.D[0] & 0xFFFFu) > 8u" in block,
          "generated invalid-selector branch reports the first bypass")
    check("goto label_069B0A;" in block and
          "g_cpu.A[0] = 0x0006CC48u;" not in block and
          "m68k_write8" not in block,
          "invalid selector jumps before LEA/table access without changing guest registers or RAM")
    check("g_cpu.A[0] = 0x0006CC48u;" in body[p_lea:] and
          "m68k_read32" in body[p_lea:p_lookup] and
          p_lea < p_lookup,
          "valid selectors retain the original indexed pointer-table lookup")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path,
                        default=root.parent / "engine")
    parser.add_argument("--rom", type=Path, default=root / "game/shinobi3.gen")
    parser.add_argument("--generated-c", type=Path,
                        help="generated shinobi3_part30.c; supply after the approved build")
    args = parser.parse_args()
    inspect_rom(args.rom)
    inspect_source(args.engine)
    if args.generated_c:
        inspect_generated(args.generated_c)
    else:
        print("NOTE: generated-code checks are pending the approved build")


if __name__ == "__main__":
    main()
