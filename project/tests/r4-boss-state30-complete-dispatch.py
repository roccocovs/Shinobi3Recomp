#!/usr/bin/env python3
"""ROM-backed regression for the verified Round 4 state-$30 action table."""
import argparse
import hashlib
import re
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
ROWS = (
    (0x00, 0x02E3CC, 0x02E3E8),
    (0x04, 0x02E3D0, 0x02E41A),
    (0x08, 0x02E3D4, 0x02E484),
    (0x0C, 0x02E3D8, 0x02E4D0),
    (0x10, 0x02E3DC, 0x02E50C),
    (0x14, 0x02E3E0, 0x02E53A),
    (0x18, 0x02E3E4, 0x02E570),
)
CURSOR_ADVANCES = (
    (0x02E410, 0x00, 0x04),
    (0x02E47E, 0x04, 0x08),
    (0x02E4CA, 0x08, 0x0C),
    (0x02E4F6, 0x0C, 0x10),
    (0x02E524, 0x10, 0x14),
    (0x02E56A, 0x14, 0x18),
)
RTS_PATHS = (
    0x02E418, 0x02E482, 0x02E4CE, 0x02E50A,
    0x02E528, 0x02E56E, 0x02E5A2,
)


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def s16(value):
    return value - 0x10000 if value & 0x8000 else value


def body(generated, address):
    name = f"func_{address:06X}"
    pattern = re.compile(rf"(?m)^void {name}\(void\)\s*\{{")
    for path in generated.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        match = pattern.search(text)
        if not match:
            continue
        depth = 0
        for pos in range(text.find("{", match.start()), len(text)):
            depth += (text[pos] == "{") - (text[pos] == "}")
            if depth == 0:
                return text[match.start():pos + 1]
    raise AssertionError(f"generated body {name} is missing")


def instruction_block(code, address):
    marker = f"/* ${address:06X} */"
    start = code.find(marker)
    need(start >= 0, f"generated instruction ${address:06X} is missing")
    next_boundary = re.search(
        r"(?m)^  (?:/\* \$[0-9A-F]{6} \*/|label_[0-9A-F]{6}:;)$",
        code[start + len(marker):])
    end = start + len(marker) + next_boundary.start() if next_boundary else len(code)
    return code[start:end]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
         "unexpected ROM image")
    state30 = body(args.generated_dir, 0x02E3C0)
    switch_match = re.search(
        r"switch \(\(int32_t\)m68k_brief_index_value\([^\n]+\) \{(.*?)\n  \}",
        state30, re.S)
    need(switch_match, "generated state-$30 computed-jump switch is missing")
    switch = switch_match.group(1)

    # State $2C stores long $00000050 at +$28. In big-endian object memory,
    # that initializes the cursor word at +$28 to zero and the adjacent timer
    # at +$2A to $50, then advances state to $30.
    # Supported-ROM digest and generated-code checks cover this path.
    state2c = body(args.generated_dir, 0x02E1EA)
    setup = instruction_block(state2c, 0x02E2A4)
    need("m68k_write32((uint32_t)(g_cpu.A[0] + (int32_t)40), "
         "(uint32_t)(0x00000050u));" in setup,
         "native state-$2C setup does not preserve the long store at +$28")
    # Supported-ROM digest and generated-code checks cover this path.
    timer_step = instruction_block(state30, 0x02E3E8)
    timer_branch = instruction_block(state30, 0x02E3EC)
    need("m68k_read16((uint32_t)(g_cpu.A[0] + (int32_t)42))" in timer_step
         and "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)42)" in timer_step
         and "if (!(g_cpu.SR & (1u<<2)))" in timer_branch
         and "goto label_02E414;" in timer_branch,
         "native cursor-zero timer path no longer gates the first +4 advance")
    jump_pc = 0x02E3C8
    extension = int.from_bytes(rom[jump_pc + 2:jump_pc + 4], "big")
    jump_base = jump_pc + 2 + (extension & 0xFF)
    need(jump_base == 0x02E3CC and extension == 0x0002,
         "state-$30 computed-jump base/index extension changed")

    expected_cases = [f"case {cursor}: goto label_{row:06X};"
                      for cursor, row, *_ in ROWS]
    expected_cases.append("case 80: goto label_02E41C;")
    actual_cases = [line.strip() for line in
                    re.findall(r"(?m)^    case .*;$", switch)]
    need(actual_cases == expected_cases,
         f"computed-jump cases differ from the verified domain: {actual_cases}")

    for cursor, row, target in ROWS:
        opcode = int.from_bytes(rom[row:row + 2], "big")
        displacement = s16(int.from_bytes(rom[row + 2:row + 4], "big"))
        need(opcode == 0x6000,
             f"cursor ${cursor:02X} row is not a word-displacement unconditional branch")
        need(row + 2 + displacement == target,
             f"cursor ${cursor:02X} row does not branch to ${target:06X}")
        need(row == jump_base + cursor,
             f"cursor ${cursor:02X} does not select row ${row:06X}")
        # Supported-ROM digest and generated-code checks cover this path.
        need(f"label_{row:06X}:;" in state30 and
             f"goto label_{target:06X};" in instruction_block(state30, row),
             f"native row ${row:06X} does not take its verified BRA.W")
        need(f"label_{target:06X}:;" in state30 and
             f"/* ${target:06X} */" in state30,
             f"native action entry ${target:06X} is not in the state-$30 body")
        need(f"recomp_call_addr(0x{row:06X}u)" not in state30 and
             f"recomp_tail_call(0x{row:06X}u)" not in state30,
             f"cursor ${cursor:02X} row was emitted as an external dispatch")

    # The only cursor increments in the $00..$18 action sequence are these
    # six conditional ROM ADDQ.W writers. Verify each complete generated
    # arithmetic/CCR/store block independently, not just its address comment.
    for pc, previous, following in CURSOR_ADVANCES:
        # Supported-ROM digest and generated-code checks cover this path.
        block = instruction_block(state30, pc)
        suffix = f"{pc:06X}"
        result = f"_{suffix}r"
        need(f"uint16_t {result} = (uint16_t)((uint16_t)(_t{suffix}) + "
             "(uint16_t)4u);" in block,
             f"native cursor update at ${pc:06X} does not add four")
        need("g_cpu.SR &= ~(0x1Fu);" in block and
             "if (!_fr)" in block and "if (_fr >> 15)" in block and
             "g_cpu.SR |= (1u<<0); g_cpu.SR |= (1u<<4);" in block and
             "g_cpu.SR |= (1u<<1);" in block,
             f"native ADDQ flags at ${pc:06X} are not represented")
        need(f"m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)40), "
             f"(uint16_t)({result}));" in block,
             f"native cursor update at ${pc:06X} does not write +$28(A0)")
        need(following == previous + 4,
             f"cursor progression at ${pc:06X} is not the next table row")

    # The last action at cursor $18 transitions to a state selected from the
    # ROM table; it does not increment to an unverified cursor-$1C row.
    # Supported-ROM digest and generated-code checks cover this path.
    addq = instruction_block(state30, 0x02E59A)
    state_store = instruction_block(state30, 0x02E59C)
    need("g_cpu.D[0] = (g_cpu.D[0] & 0xFFFF0000u)" in addq and
         "m68k_read16((uint32_t)(0x0002E59E + " in state_store and
         "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)4)" in state_store,
         "terminal action no longer follows the ROM state-selection table")
    need(sum(1 for pc, _, _ in CURSOR_ADVANCES
             if f"m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)40), "
             f"(uint16_t)(_{pc:06X}r));" in state30) == 6,
         "state-$30 body does not contain exactly the six verified cursor stores")

    # Preserve the cursor-$50 overlapping ORI-to-CCR stream and fallback for
    # every unverified value. It is separate from the $00..$18 progression.
    need(("case 80: goto label_02E41C;" in switch and "g_cpu.SR |= 0x29u; /* ORI #imm,CCR */" in state30),
         "cursor $50 overlapping ORI-to-CCR route was changed")
    need("default:" in switch and
         "hybrid_jmp_interpret(0x0002E3CCu + "
         "m68k_brief_index_value(0x0002u, g_cpu.D[0], g_cpu.A[0]));" in state30,
         "unverified computed-jump indices lost their existing fallback")

    # Each legitimate state-$30 action returns with RTS. Verify the guest
    # opcode and that native return handling still recognizes the synthetic
    # $02EE38 continuation at that exact epilogue.
    for pc in RTS_PATHS:
        need(int.from_bytes(rom[pc:pc + 2], "big") == 0x4E75,
             f"RTS instruction missing at ${pc:06X}")
        block = instruction_block(state30, pc)
        need("m68k_read32(g_cpu.A[7]) == 0x02EE38u" in block and
             "g_cpu.A[7] += 4;" in block and
             "recomp_tail_call(0x02EE38u); return;" in block,
             f"RTS at ${pc:06X} no longer consumes the synthetic PEA return")
        need("g_rte_pending = _sp_popped;" in block or
             "g_rte_pending = g_split_sp_popped;" in block,
             f"RTS at ${pc:06X} lost ordinary guest-return bookkeeping")

    # The computed JMP and its BRA.W rows do not modify guest registers, CCR,
    # A7, or memory. Their generated local routing must be only a C goto.
    for cursor, row, *_ in ROWS:
        block = instruction_block(state30, row)
        native_lines = [line.strip() for line in block.splitlines()
                        if line.strip() and not line.strip().startswith("/*")]
        guest_effects = [line for line in native_lines
                         if not line.startswith("g_native_insn_count++;")
                         and not line.startswith("GEN_COSIM_TICK(")
                         and not re.fullmatch(r"g_r4_scroll_trace_current_pc = 0x[0-9A-F]{6}u;", line)
                         and not re.fullmatch(r"goto label_[0-9A-F]{6};", line)]
        need(len(re.findall(r"(?m)^\s*goto label_[0-9A-F]{6};$", block)) == 1
             and not guest_effects,
            f"row ${row:06X} has native side effects beyond the original BRA.W")

    print("PASS: ROM-verified cursor rows $00..$18 and $50 compile as exact local branches")
    print("PASS: all six ADDQ.W cursor producers retain their value, CCR, and memory effects")
    print("PASS: terminal state transition, seven RTS/PEA paths, and unknown-index fallback are preserved")


if __name__ == "__main__":
    main()
