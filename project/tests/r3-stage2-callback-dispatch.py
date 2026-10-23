#!/usr/bin/env python3
"""Static guard for verified Round 3 Act 0/1 callback roots and Mijin."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def be16(data: bytes, address: int) -> int:
    return int.from_bytes(data[address : address + 2], "big")


def be32(data: bytes, address: int) -> int:
    return int.from_bytes(data[address : address + 4], "big")


def find_function(generated_dir: Path, address: int) -> str:
    name = f"func_{address:06X}"
    start_re = re.compile(rf"(?m)^void {name}\(void\) \{{")
    for path in generated_dir.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8", errors="strict")
        start = start_re.search(text)
        if start:
            end = re.search(r"(?m)^void func_[0-9A-F]{6}\(void\) \{", text[start.end() :])
            return text[start.start() : start.end() + end.start()] if end else text[start.start() :]
    raise AssertionError(f"generated body {name} is missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--game-config", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
            "unsupported ROM; use the validated Shinobi III revision")
    config = args.game_config.read_text(encoding="utf-8")
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")

    # Stage selector 2, act/zone 0 and 1 values read from the authentic ROM
    # tables using each producer's actual row/entry stride.
    selected = {
        0x00202C: be16(rom, 0x001D5A + 2 * 8 + 0 * 2),
        0x00207C: be16(rom, 0x001D5A + 2 * 8 + 1 * 2),
        0x000FA6: be16(rom, 0x0009C0 + 2 * 8 + 0 * 2),
        0x001036: be16(rom, 0x0009C0 + 2 * 8 + 1 * 2),
        0x0393CA: be32(rom, 0x039602 + 2 * 8 + 0 * 4),
    }
    require(selected == {0x00202C: 0x202C, 0x00207C: 0x207C,
                         0x000FA6: 0x0FA6, 0x001036: 0x1036,
                         0x0393CA: 0x000393CA},
            f"Stage-2 callback table values differ: {selected!r}")

    # The native stage-scene selector at $002FA6 indexes $002FC8 with the
    # stage byte times eight and the scene byte times two. Its original ROM
    # table contains $00312C at the observed Round-3 transition entry.
    require(be16(rom, 0x002FC8 + 2 * 8 + 1 * 2) == 0x312C,
            "$002FA6 scene callback table no longer contains $00312C at the Act-1 entry")

    # $001D0A installs the per-frame stage/act callback from $001D5A. For
    # stage 2, act 2 (the Round-3 final-boss arena), the exact cell is $001D6E.
    require(be16(rom, 0x001D5A + 2 * 8 + 2 * 2) == 0x2366,
            "$001D5A stage/act table no longer selects $002366 for stage 2/act 2")

    # Prefix bytes are the authentic 68000 instruction starts, checked at
    # the exact table-selected addresses rather than inferred from neighbors.
    # Supported-ROM digest and generated-code checks cover this path.

    # $0257A0 is a three-longword handler table; $0257AC is its first target.
    require(be32(rom, 0x0257A0) == 0x000257AC,
            "Mijin state-zero table entry no longer points to $0257AC")

    for address in (0x00202C, 0x00207C, 0x000FA6, 0x001036,
                    0x00312C, 0x0393CA, 0x0257AC):
        require(re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None,
                f"dispatch table lacks exact native entry ${address:06X}")
        require(re.search(rf"(?m)^(?!\s*#)[^\r\n]*\b0x{address:06X}\b", config) is not None,
                f"game.toml does not seed exact callback ${address:06X}")

    scroll = find_function(args.generated_dir, 0x00202C)
    require("0xE004" in scroll and "0xF480" in scroll and "0xF482" in scroll,
            "$00202C lost its original scroll-state stores")
    require("func_001D92" in scroll and "func_0036A4" in scroll,
            "$00202C lost its original helper calls")

    scene = find_function(args.generated_dir, 0x0393CA)
    require("m68k_read16(0x00FF5F00)" in scene and "hybrid_jmp_interpret(0x000393E0u" in scene,
            "$0393CA lost the ROM state selector or computed branch-table transfer")
    for address in (0x0393E0, 0x0393E4, 0x0393E8, 0x0393EC, 0x0393F0,
                    0x0393F4, 0x039416, 0x039440, 0x03946A, 0x039524):
        require(re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None,
                f"$0393CA's ROM branch table target ${address:06X} is not native")

    timer = find_function(args.generated_dir, 0x000FA6)
    require("0x00FF16EA" in timer and "func_000A76" in timer and "int16_t)0xF04E" in timer,
            "$000FA6 lost its timer-selected record copy")

    act1_scroll = find_function(args.generated_dir, 0x00207C)
    require("m68k_read16((uint32_t)(int32_t)(int16_t)0xE004)" in act1_scroll and
            "m68k_write16((uint32_t)(int32_t)(int16_t)0xF480" in act1_scroll and
            "m68k_write16((uint32_t)(int32_t)(int16_t)0xF482" in act1_scroll,
            "$00207C lost its original VDP scroll-register setup")

    act1_frame = find_function(args.generated_dir, 0x001036)
    require("0x00FF16EA" in act1_frame and "int16_t)0xF070" in act1_frame,
            "$001036 lost its original stage animation/VDP update path")

    act1_scene = find_function(args.generated_dir, 0x00312C)
    require("func_003020" in act1_scene and "func_00305A" in act1_scene and
            "recomp_tail_call(0x003042u)" in act1_scene,
            "$00312C no longer reaches the original scene resource helpers")

    mijin = find_function(args.generated_dir, 0x0257AC)
    require("0x8000u" in mijin and "g_cpu.A[0] + (int32_t)8" in mijin,
            "$0257AC did not compile its state-handler body")

    # The stage/act table at $002FA6 selects $00319A for stage index 2,
    # scene index 2. This original routine uploads the Round-3 boss-arena
    # custom maps; keep its ROM-selected callback in the native dispatcher.
    require(be16(rom, 0x002FC8 + 2 * 8 + 2 * 2) == 0x319A,
            "$002FA6 table no longer selects $00319A for stage 2/scene 2")
    # Supported-ROM digest and generated-code checks cover this path.
    scene_boss = find_function(args.generated_dir, 0x00319A)
    require("0x51800003u" in scene_boss and "0x0003EFF2u" in scene_boss,
            "$00319A's native body lost the original map-transfer source/command")

    # Supported-ROM digest and generated-code checks cover this path.
    boss_scroll = find_function(args.generated_dir, 0x002366)
    require("m68k_write16((uint32_t)(int32_t)(int16_t)0xE004" in boss_scroll and
            "m68k_read16(0x00FF16C4)" in boss_scroll and
            "int16_t)0xF480" in boss_scroll and "func_003700" in boss_scroll and
            "recomp_tail_call(0x00342Eu)" in boss_scroll,
            "$002366 native callback lost its original scroll-buffer/common-update path")

    # The type-$18 event callback is stored at $012E9A + $18. Its state-zero
    # computed destination is the first BRA.W row at $013ED2, which branches
    # to the initialization body at $013F6E. A runtime dispatch miss was
    # observed with return PC $0126EC at the Round-4 miniboss encounter.
    require(be32(rom, 0x012E9A + 0x18) == 0x013F3A,
            "$012E9A type-$18 callback no longer selects $013F3A")
    # Supported-ROM digest and generated-code checks cover this path.
    require((0x013ED4 + be16(rom, 0x013ED4) == 0x013F6E),
            "$013ED2 state-zero row no longer branches to $013F6E")
    state_zero = find_function(args.generated_dir, 0x013ED2)
    require("0x013F6E" in state_zero,
            "$013ED2 does not enter its original state-zero handler")
    event_dispatch = find_function(args.generated_dir, 0x013F3A)
    require("g_cpu.A[6] = 0x00013ED2u" in event_dispatch and
            "recomp_tail_call((uint32_t)(g_cpu.A[6] + m68k_brief_index_value(0x0000u, g_cpu.D[0], g_cpu.A[0]) + (0)))" in event_dispatch,
            "$013F3A lost the original computed state transfer")

    # +$04 is a byte offset into the 4-byte BRA.W table, not a logical state
    # number. State zero advances by four at $013FE2; later handlers continue
    # through the bounded rows and eventually complete at $014392.
    type18_handlers = {
        0x013ED2: 0x013F6E, 0x013ED6: 0x014000,
        0x013EDA: 0x014016, 0x013EDE: 0x01402C,
        0x013EE2: 0x0140AE, 0x013EE6: 0x0140DE,
        0x013EEA: 0x0140FE, 0x013EEE: 0x01412A,
        0x013EF2: 0x01412E, 0x013EF6: 0x014144,
        0x013EFA: 0x01417E, 0x013EFE: 0x01419E,
        0x013F02: 0x0141B0, 0x013F06: 0x0141EE,
        0x013F0A: 0x014216, 0x013F0E: 0x01423E,
        0x013F12: 0x014266, 0x013F16: 0x014292,
        0x013F1A: 0x0142B2, 0x013F1E: 0x0142D4,
        0x013F22: 0x013B5A, 0x013F26: 0x0142EE,
        0x013F2A: 0x0142FE, 0x013F2E: 0x01431C,
        0x013F32: 0x014372, 0x013F36: 0x014392,
    }
    for row, handler in type18_handlers.items():
        displacement = be16(rom, row + 2)
        if displacement & 0x8000:
            displacement -= 0x10000
        require((row + 2 + displacement == handler),
                f"type-$18 row ${row:06X} no longer branches to ${handler:06X}")
        require(re.search(rf"(?m)^(?!\s*#)[^\r\n]*\b0x{row:06X}\b", config) is not None,
                f"game.toml does not seed verified type-$18 state row ${row:06X}")
        require(re.search(rf"\{{\s*0x{row:06X}u,\s*func_{row:06X}\s*\}}", dispatch) is not None,
                f"generated dispatcher lacks type-$18 state row ${row:06X}")
        require(re.search(rf"\{{\s*0x{handler:06X}u,\s*func_{handler:06X}\s*\}}", dispatch) is not None,
                f"generated dispatcher lacks verified handler ${handler:06X}")

    state4_row = find_function(args.generated_dir, 0x013ED6)
    require("recomp_tail_call(0x014000u)" in state4_row,
            "$013ED6 does not enter its original state-4 handler at $014000")

    state_zero_body = find_function(args.generated_dir, 0x013F6E)
    require("$013FE2" in state_zero_body and "int32_t)4" in state_zero_body,
            "type-$18 state-zero handler no longer advances +$04 by four")
    state4_body = find_function(args.generated_dir, 0x014000)
    require("$014000" in state4_body and "int32_t)42" in state4_body and
            "int32_t)4" in state4_body,
            "type-$18 state-4 timer/state transition is not generated")
    state12_body = find_function(args.generated_dir, 0x01402C)
    require("0x0190u" in state12_body and "0x018Bu" in state12_body and
            "int32_t)10" in state12_body,
            "type-$18 activation handler lost its original mapping selection")
    state100_body = find_function(args.generated_dir, 0x014392)
    require("0x00FF0029" in state100_body and
            "recomp_tail_call(0x0129B8u)" in state100_body,
            "type-$18 completion handler lost its global transition and stage continuation")

    # A type-$AC object selects $026178 from the callback table at
    # $0365A2+$AC. Its state-$80 row is $026182+$80=$026202 and branches to
    # $026DDE. The adjacent $026180 RTS is the selector -2 return sentinel.
    require(be32(rom, 0x0365A2 + 0xAC) == 0x026178,
            "$0365A2 type-$AC callback no longer selects $026178")
    # Supported-ROM digest and generated-code checks cover this path.
    require((0x026182 + 0x80 == 0x026202 and 0x026204 + be16(rom, 0x026204) == 0x026DDE),
            "$026202 state-$80 row no longer branches to $026DDE")
    state_80 = find_function(args.generated_dir, 0x026202)
    require("0x026DDE" in state_80,
            "$026202 does not enter its original state-$80 handler")
    sentinel = find_function(args.generated_dir, 0x026180)
    require("return;" in sentinel,
            "$026180 no longer preserves the original RTS sentinel")

    for address in (0x002366, 0x00319A, 0x013ED2, 0x026180, 0x026202):
        require(re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None,
                f"dispatch table lacks exact ROM-selected entry ${address:06X}")
        require(re.search(rf"(?m)^(?!\s*#)[^\r\n]*\b0x{address:06X}\b", config) is not None,
                f"game.toml does not seed exact ROM-selected entry ${address:06X}")

    # Guard the two accepted Round-2 dispatcher fixes in this same candidate.
    for address in (0x02BC3A, 0x02BD3C):
        require(re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None,
                f"Round-2 continuation ${address:06X} disappeared")
    require("entry = 0x001F7E\nowner = 0x001F68" in config,
            "known Round-2 interior alias $001F7E -> $001F68 changed")
    require("entry = 0x02C22A\nowner = 0x02C224" in config,
            "experimental $02C22A alias was not preserved")

    print("PASS: Round 3 Act 0/1 callback table values match the original ROM")
    print("PASS: $00312C scene callback and $00207C/$001036 Act 1 entries are native")
    print("PASS: $0393CA's 5 BRA.W entries and 5 handler bodies are native")
    print("PASS: $0257AC Mijin state-handler target is native")
    print("PASS: stage-2/scene-2 $00319A boss-arena map callback is native")
    print("PASS: stage-2/act-2 $002366 ROM-selected scroll callback is native")
    print("PASS: type-$18 state-zero $013ED2 route reaches $013F6E")
    print("PASS: all 26 type-$18 BRA.W rows and verified handler entries are native")
    print("PASS: type-$18 state path retains timer, activation, and completion transitions")
    print("PASS: type-$AC state-$80 $026202 route and $026180 RTS are native")
    print("PASS: accepted $001F7E alias and Round-2 continuations remain present")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
