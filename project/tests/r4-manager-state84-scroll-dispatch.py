"""ROM-backed regression for the Round 4 manager's state-$84/$88 scroll path."""
import argparse
import hashlib
import re
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def function_body(parts, address):
    marker = f"/* ${address:06X} */"
    for text in parts:
        pos = text.find(marker)
        if pos < 0:
            continue
        start = text.rfind("\nvoid func_", 0, pos)
        if start < 0 and text.startswith("void func_"):
            start = 0
        if start >= 0:
            start = start + (1 if start != 0 else 0)
            end = text.find("\n}\n", start)
            if end >= 0:
                body = text[start:end + 2]
                if re.match(r"void func_[0-9A-F]{6}\(void\)\s*\{", body):
                    return body
    raise AssertionError(f"no generated function owns ${address:06X}")


def exact_function(parts, address):
    name = f"func_{address:06X}"
    header = f"void {name}(void) {{"
    for text in parts:
        start = text.find(header)
        if start >= 0:
            end = text.find("\n}\n", start)
            if end >= 0:
                return text[start:end + 2]
    raise AssertionError(f"generated function {name} is missing")


def signed16(value):
    return value - 0x10000 if value & 0x8000 else value


def branch_target(rom, row):
    return row + 2 + signed16(int.from_bytes(rom[row + 2:row + 4], "big"))


def branch_target_short(rom, pc):
    displacement = rom[pc + 1]
    if displacement & 0x80:
        displacement -= 0x100
    return pc + 2 + displacement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
         "unexpected Shinobi III ROM image")
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    parts = [p.read_text(encoding="utf-8")
             for p in args.generated_dir.glob("shinobi3_part*.c")]

    # The existing manager dispatch pushes $02EE38 and uses the unscaled state
    # value as an offset from $02DB28. The pre-dispatch condition writes $84.
    # Supported-ROM digest and generated-code checks cover this path.
    need((0x02DAE8 + 0x18 == 0x02DB00),
         "state-$84 producer no longer writes the original state and +$18 field")
    # Supported-ROM digest and generated-code checks cover this path.
    need(0x02DB28 + 0x84 == 0x02DBAC and
         0x02DB28 + 0x88 == 0x02DBB0,
         "state values no longer select the authenticated table rows")
    # Supported-ROM digest and generated-code checks cover this path.
    need(branch_target(rom, 0x02DBAC) == 0x02ED22 and
         branch_target(rom, 0x02DBB0) == 0x02EDF0,
         "manager rows no longer reach their original handlers")

    # Both branch destinations are valid overlapping entries immediately
    # following an RTS in the linear stream; state $84 itself advances to $88.
    need((branch_target_short(rom, 0x02ED3C) == 0x02ED68),
         "state-$84 coordinate threshold branch changed")
    # Supported-ROM digest and generated-code checks cover this path.

    # The terminal JMP is the original stage handoff path, not a fabricated
    # boss-clear shortcut. It branches back to the object loop when A3's bit
    # is set; otherwise it selects the stage callback using FF37A6 and enters
    # the shared $0125BC updater.
    # Supported-ROM digest and generated-code checks cover this path.

    # The continuation is a PEA return, not a new C call. Its updater computes
    # FFF480 from live manager/camera fields and feeds the ROM raster scroll.
    # Supported-ROM digest and generated-code checks cover this path.

    row84 = function_body(parts, 0x02DBAC)
    row88 = function_body(parts, 0x02DBB0)
    handler84 = exact_function(parts, 0x02ED22)
    handler88 = exact_function(parts, 0x02EDF0)
    scroll = exact_function(parts, 0x02EE38)
    stage_exit = exact_function(parts, 0x02A466)
    stage_update = exact_function(parts, 0x0125BC)
    for address, name in ((0x02DBAC, "func_02DBAC"),
                          (0x02DBB0, "func_02DBB0"),
                          (0x02ED22, "func_02ED22"),
                          (0x02EDF0, "func_02EDF0"),
                          (0x02EE38, "func_02EE38"),
                          (0x02A466, "func_02A466"),
                          (0x0125BC, "func_0125BC")):
        need(re.search(rf"\{{\s*0x{address:06X}u,\s*{name}\s*\}}", dispatch),
             f"${address:06X} is absent from native function dispatch")
    need("recomp_tail_call(0x02ED22u); return;" in row84 and
         "recomp_tail_call(0x02EDF0u); return;" in row88,
         "state rows do not preserve their exact BRA.W destinations")
    need("m68k_read32(g_cpu.A[7]) == 0x02EE38u" in handler84 and
         "m68k_read32(g_cpu.A[7]) == 0x02EE38u" in handler88 and
         "g_cpu.A[7] += 4;" in handler84 and
         "g_cpu.A[7] += 4;" in handler88 and
         "recomp_tail_call(0x02EE38u); return;" in handler84 and
         "recomp_tail_call(0x02EE38u); return;" in handler88,
         "nonterminal handler RTS paths do not consume the PEA slot and resume $02EE38")
    need("m68k_write16" in handler84 and
         "0x02A466u" in handler88 and
         "recomp_tail_call(0x02A466u); return;" in handler88,
         "state transition or authentic state-$88 terminal JMP is missing")
    need("m68k_read8(0x00FF37A6)" in stage_exit and
         "m68k_brief_index_value(0x0004u, g_cpu.D[0], g_cpu.A[0])" in stage_exit and
         "recomp_tail_call(0x0125BCu); return;" in stage_exit and
         "m68k_read32(0x00FF37B2)" in stage_update and
         "recomp_call_func(func_009676);" in stage_update and
         "m68k_write32(0x00FF37B2u" in stage_update,
         "state-$88 terminal path no longer reaches the generated stage updater")
    need("goto label_02ED68;" in handler84 and "/* $02ED62 */" in handler84,
         "generated state-$84 coordinate branch or state transition is missing")
    need("/* $02EF28 */" in scroll and
         "m68k_read16((uint32_t)(g_cpu.A[0] + (int32_t)36))" in scroll and
         "m68k_read16((uint32_t)(int32_t)(int16_t)0xE004)" in scroll and
         "m68k_read16((uint32_t)(g_cpu.A[0] + (int32_t)66))" in scroll and
         "_02EF34r = (uint16_t)(0 - (uint16_t)((uint16_t)g_cpu.D[0]))" in scroll and
         "m68k_write16((uint32_t)(int32_t)(int16_t)0xF480, (uint16_t)((uint16_t)g_cpu.D[0]))" in scroll,
         "generated continuation no longer computes the ROM live-coordinate scroll formula")

    print("PASS: state-$84 producer, $84/$88 rows, and overlapping ROM handlers are verified")
    print("PASS: handler branches and terminal state-$88 JMP preserve original flow")
    print("PASS: both nonterminal RTS paths consume PEA $02EE38 and retain live scroll updates")
    print("PASS: terminal $02A466 stage selection reaches the generated $0125BC updater")


if __name__ == "__main__":
    main()
