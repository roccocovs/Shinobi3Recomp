#!/usr/bin/env python3
"""ROM-backed checks for the Round 4 manager state closure and exact EFC0 entry."""
import argparse
import hashlib
import re
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
ROWS = (
    (0x34, 0x02DB5C, 0x02E5B0), (0x38, 0x02DB60, 0x02E600),
    (0x3C, 0x02DB64, 0x02E6C8), (0x40, 0x02DB68, 0x02E732),
    (0x44, 0x02DB6C, 0x02E7B2), (0x48, 0x02DB70, None),
    (0x4C, 0x02DB74, None), (0x50, 0x02DB78, 0x02E842),
    (0x54, 0x02DB7C, None), (0x58, 0x02DB80, 0x02E8C4),
    (0x5C, 0x02DB84, 0x02E988), (0x64, 0x02DB8C, 0x02E9F6),
    (0x68, 0x02DB90, 0x02EA5A), (0x6C, 0x02DB94, 0x02EABC),
    (0x70, 0x02DB98, 0x02EAFE), (0x74, 0x02DB9C, 0x02EC4C),
    (0x78, 0x02DBA0, 0x02EC52), (0x7C, 0x02DBA4, 0x02EC60),
    (0x80, 0x02DBA8, 0x02ECC4),
)
INTERPOLATION_CALLERS = (
    0x02E4D0, 0x02E50C, 0x02E518,
)


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def s16(value):
    return value - 0x10000 if value & 0x8000 else value


def _function_slice(text, header_start):
    body_open = text.find("{", header_start)
    close = text.find("\n}\n", body_open)
    if close < 0:
        raise AssertionError("unterminated generated C function")
    return text[header_start:close + 2]


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
            block = _function_slice(text, start)
            match = re.match(r"void (func_[0-9A-F]{6})\(void\)\s*\{", block)
            if match:
                return match.group(1), block
    raise AssertionError(f"no generated function owns instruction ${address:06X}")


def exact_function(parts, address):
    name = f"func_{address:06X}"
    header = f"void {name}(void) {{"
    for text in parts:
        pos = text.find(header)
        if pos >= 0:
            return _function_slice(text, pos)
    raise AssertionError(f"generated function {name} is missing")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256, "unexpected ROM image")
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    parts = [p.read_text(encoding="utf-8")
             for p in args.generated_dir.glob("shinobi3_part*.c")]

    # The manager pushes its authentic $02EE38 synthetic continuation, then
    # indexes the table at $02DB28 by the state word at object +$04.
    # Supported-ROM digest and generated-code checks cover this path.
    row_functions = {}
    admitted = set()
    for state, row, target in ROWS:
        opcode = int.from_bytes(rom[row:row + 2], "big")
        need(row == 0x02DB28 + state,
             f"state ${state:02X} row offset no longer matches the state table")
        row_name, row_body = function_body(parts, row)
        need(f"{{ 0x{row:06X}u, {row_name} }}" in dispatch,
             f"state ${state:02X} row is absent from native address dispatch")
        if target is None:
            next_row = {0x48: 0x02DB74, 0x4C: 0x02DB78, 0x54: 0x02DB80}[state]
            ext = int.from_bytes(rom[row + 2:row + 4], "big")
            need((opcode & 0xF1C0) == 0x5040 and ((opcode >> 9) & 7) == 4 and
                 ((opcode >> 6) & 3) == 1 and ((opcode >> 3) & 7) == 5 and
                 (opcode & 7) == 0 and ext == 4 and row + 4 == next_row,
                 f"state ${state:02X} is not ADDQ.W #4,(4,A0)")
            need("m68k_read16((uint32_t)(g_cpu.A[0] + (int32_t)4))" in row_body and
                 "(uint16_t)(_" in row_body and
                 f"m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)4)" in row_body,
                 f"state ${state:02X} ADDQ did not retain its +$04 word update")
            need("g_cpu.SR &= ~(0x1Fu)" in row_body and
                 "g_cpu.SR |= (1u<<0)" in row_body and
                 "g_cpu.SR |= (1u<<4)" in row_body and
                 "g_cpu.SR |= (1u<<1)" in row_body,
                 f"state ${state:02X} ADDQ did not retain CCR effects")
            need(f"recomp_tail_call(0x{next_row:06X}u); return;" in row_body,
                 f"state ${state:02X} does not continue at exact next ROM row")
            admitted.add(state)
            continue

        displacement = s16(int.from_bytes(rom[row + 2:row + 4], "big"))
        need(opcode == 0x6000,
             f"state ${state:02X} row is not an unconditional word branch")
        need(row + 2 + displacement == target,
             f"state ${state:02X} branch destination changed")
        # Supported-ROM digest and generated-code checks cover this path.
        target_name, target_body = function_body(parts, target)
        need(f"{{ 0x{target:06X}u, {target_name} }}" in dispatch,
             f"handler ${target:06X} is absent from native address dispatch")
        need(f"recomp_tail_call(0x{target:06X}u); return;" in row_body,
             f"state ${state:02X} row does not branch to its exact handler")
        need("m68k_read32(g_cpu.A[7]) == 0x02EE38u" in target_body and
             "g_cpu.A[7] += 4;" in target_body and
             "recomp_tail_call(0x02EE38u); return;" in target_body,
             f"handler ${target:06X} lost manager PEA/RTS continuation")
        admitted.add(state)

    # Verify the table's bounded state domain, including the initial values
    # and every exact +$04 state writer/ADDQ row in the authentic closure.
    reachable = {0x34, 0x44, 0x64, 0x74}
    transitions = {
        0x34: (0x38,), 0x38: (0x3C,), 0x3C: (0x40,), 0x40: (0x44,),
        0x44: (0x48,), 0x48: (0x4C,), 0x4C: (0x50,), 0x50: (0x5C,),
        0x54: (0x58,), 0x58: (0x44,), 0x5C: (0x7C,), 0x64: (0x68,),
        0x68: (0x6C,), 0x6C: (0x70,), 0x70: (0x54,), 0x74: (0x78,),
        0x78: (0x6C,), 0x7C: (0x80,), 0x80: (0x30,),
    }
    pending = list(reachable)
    while pending:
        for following in transitions.get(pending.pop(), ()):
            if following not in reachable:
                reachable.add(following)
                pending.append(following)
    need(reachable - {0x30} == admitted,
         f"admitted state closure differs from verified graph: {sorted(reachable)}")
    need(not ({0x60, 0x84, 0x88} & admitted),
         "unproven adjacent table rows were added")

    # E5B0 is the state-$34 handler. Its first branch is controlled by
    # $FF5ECE; the body must retain the same conditional and stack continuation.
    e5b0 = exact_function(parts, 0x02E5B0)
    need("m68k_read16(0x00FF5ECE)" in e5b0,
         "$02E5B0 no longer reads the verified manager condition")
    need("if (!(g_cpu.SR & (1u<<3)))" in e5b0 and
         "recomp_call_func(func_02EFBE);" in e5b0,
         "$02E5B0 condition or its original helper route changed")

    # Three ROM BSR.Ws start at caller +6, target EFC0 and return at caller+10.
    # Before this correction, codegen failed to add that exact interior entry.
    for caller in INTERPOLATION_CALLERS:
        bsr = caller + 6
        need((int.from_bytes(rom[bsr:bsr + 2], "big") & 0xFF00) == 0x6100,
             f"EFC0 caller ${caller:06X} no longer uses BSR")
        displacement = s16(int.from_bytes(rom[bsr + 2:bsr + 4], "big"))
        need((bsr + 2 + displacement == 0x02EFC0 and bsr + 4 == caller + 10),
             f"BSR at ${bsr:06X} no longer enters EFC0 and returns to its authentic continuation")
        owner, caller_body = function_body(parts, bsr)
        need(f"recomp_push_return(0x{caller + 10:06X}u)" in caller_body and
             "recomp_call_func(func_02EFC0);" in caller_body and
             "recomp_call_addr(0x02EFC0u)" not in caller_body,
             f"BSR at ${bsr:06X} still uses unsupported address dispatch")
        need(owner.startswith("func_"),
             f"BSR caller ${bsr:06X} is not inside a compiled function")

    efbe = exact_function(parts, 0x02EFBE)
    efc0 = exact_function(parts, 0x02EFC0)
    need("/* $02EFBE */" in efbe and "m68k_read16(g_cpu.A[2])" in efbe and
         "g_cpu.A[2] += 2;" in efbe and "g_cpu.D[7] =" in efbe and
         "g_cpu.SR &= ~(0x0Fu)" in efbe and
         "recomp_tail_call(0x02EFC0u); return;" in efbe and
         "/* $02EFC0 */" not in efbe,
         "$02EFBE must preserve MOVE.W (A2)+,D7 before falling through")
    need("/* $02EFC0 */" in efc0 and "/* $02EFBE */" not in efc0 and
         "g_cpu.A[1] = (uint32_t)(g_cpu.A[0]);" in efc0 and
         "m68k_write16((uint32_t)(g_cpu.A[1] + (int32_t)54)" in efc0 and
         "m68k_write16((uint32_t)(g_cpu.A[1] + (int32_t)56)" in efc0 and
         "/* $02EFFA */" in efc0,
         "$02EFC0 entry/body or its interpolation writes are missing")
    need("g_split_sp_popped < 0 && m68k_read32(g_cpu.A[7]) == 0x02EE38u" in efc0 and
         "recomp_tail_call(0x02EE38u); return;" in efc0 and
         efc0.rfind("  return;") > efc0.find("recomp_tail_call(0x02EE38u); return;"),
         "$02EFFA must select $02EE38 only for its exact manager stack word")
    state38 = exact_function(parts, 0x02E600)
    state38_bra = s16(int.from_bytes(rom[0x02E644:0x02E646], "big"))
    need((0x02E644 + state38_bra == 0x02EFBE and "/* $02E642 */" in state38 and re.search(r"recomp_tail_call\(0x02EFBEu\);\s*return;", state38)),
         "state-$38 route no longer reaches the authentic interpolation/RTS owner")
    need("g_cpu.A[0] =" not in state38 and
         "g_cpu.A[0] =" not in efbe and
         "g_cpu.A[0] =" not in efc0,
         "state-$38 manager A0 must survive the interpolation route to $02EE38")
    state3c = exact_function(parts, 0x02E6C8)
    bsr_pc = 0x02E6E0
    displacement = s16(int.from_bytes(rom[bsr_pc + 2:bsr_pc + 4], "big"))
    need((bsr_pc + 2 + displacement == 0x02EFBE and "recomp_push_return(0x02E6E4u)" in state3c and "recomp_call_func(func_02EFBE);" in state3c),
         "$02EFC0's state-$3C local BSR/RTS path must keep its own return word")
    need(re.search(r"\{\s*0x02EFBEu,\s*func_02EFBE\s*\}", dispatch) and
         re.search(r"\{\s*0x02EFC0u,\s*func_02EFC0\s*\}", dispatch),
         "both authentic interpolation entries must remain independently addressable")

    print("PASS: $02DB5C state-$34 route and verified manager-state closure")
    print("PASS: ADDQ.W fallthroughs retain memory, CCR, and next-row semantics")
    print("PASS: manager handler keeps conditional $02EE38 PEA/RTS return")
    print("PASS: EFC0 callers now enter the exact compiled label with correct return PC")
    print("PASS: EFBE and EFC0 remain distinct entries; interpolation writes are generated")


if __name__ == "__main__":
    main()


