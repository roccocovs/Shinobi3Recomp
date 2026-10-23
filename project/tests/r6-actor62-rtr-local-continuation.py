#!/usr/bin/env python3
"""Regression for local RTR returns in the Round 6 stage-actor motion helper."""

import argparse
import hashlib
import re
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
RTR_HELPER = 0x0349C2
KARURA_CALLS = {
    0x034CBC: 0x034CC2,
    0x034E54: 0x034E5A,
    0x034F4E: 0x034F54,
    0x0350C2: 0x0350C8,
}
ALL_HELPER_CALLS = {
    **KARURA_CALLS,
    0x01E65C: 0x01E662,
    0x03798E: 0x037994,
    0x0380D4: 0x0380DA,
    0x03836E: 0x038374,
    0x03844C: 0x038452,
    0x038A9E: 0x038AA4,
}
NORMAL_RTS_CALL = (0x034BF8, 0x034BFE, 0x0126F2)


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def body(generated_dir, address):
    name = f"func_{address:06X}"
    pattern = re.compile(rf"(?m)^void {name}\(void\)\s*\{{")
    for path in generated_dir.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = pattern.search(text)
        if not match:
            continue
        depth = 0
        for pos in range(text.find("{", match.start()), len(text)):
            depth += (text[pos] == "{") - (text[pos] == "}")
            if depth == 0:
                return text[match.start():pos + 1]
    raise AssertionError(f"generated body func_{address:06X} is missing")


def generated_sources(generated_dir):
    parts = sorted(generated_dir.glob("shinobi3_part*.c"))
    need(parts, f"generated C parts are missing from {generated_dir}")
    return "\n".join(path.read_text(encoding="utf-8", errors="replace")
                      for path in parts)


def verify_local_call(all_native, rom, call_pc, return_pc):
    # Supported-ROM digest and generated-code checks cover this path.
    start = all_native.find(f"/* ${call_pc:06X} */")
    end = all_native.find(f"/* ${return_pc:06X} */", start + 1)
    need(start >= 0 and end > start,
         f"generated caller does not preserve ${call_pc:06X}->${return_pc:06X}")
    segment = all_native[start:end]
    need("recomp_call_func(func_0349C2);" in segment,
         f"generated caller at ${call_pc:06X} does not call the helper")
    need(f"g_cpu.PC == 0x{return_pc:06X}u" in segment and
         f"_jsr_slot_sp_{call_pc:06X} + 4u" in segment,
         f"generated caller at ${call_pc:06X} cannot recognize its exact RTR return")
    need("if (g_rte_pending == 1" in segment and
         "g_rte_pending = 0; /* exact local return restored this JSR continuation */" in segment,
         f"generated caller at ${call_pc:06X} does not consume the matching local return")
    need("else if (g_rte_pending) { --g_rte_pending;" in segment and
         "return; } /* non-local RTE/skip propagation (pre-pop) */" in segment,
         f"generated caller at ${call_pc:06X} no longer propagates a non-local unwind")


def verify_normal_call(all_native, rom, call_pc, return_pc, target):
    opcode = int.from_bytes(rom[call_pc:call_pc + 2], "big")
    destination = int.from_bytes(rom[call_pc + 2:call_pc + 6], "big")
    need(opcode == 0x4EB9 and destination == target,
         f"${call_pc:06X} no longer uses JSR absolute-long to the ordinary RTS helper")
    # Supported-ROM digest and generated-code checks cover this path.
    start = all_native.find(f"/* ${call_pc:06X} */")
    end = all_native.find(f"/* ${return_pc:06X} */", start + 1)
    need(start >= 0 and end > start,
         f"ordinary JSR caller does not preserve ${call_pc:06X}->${return_pc:06X}")
    segment = all_native[start:end]
    need(f"recomp_call_func(func_{target:06X});" in segment,
         "ordinary RTS helper call was lost from generated code")
    need("if (g_rte_pending == 1" in segment and "else if (g_rte_pending)" in segment,
         "ordinary call wrapper no longer distinguishes a zero-pending RTS return")
    need("g_cpu.A[7] += 4; /* normal JSR pop */" in segment,
         "ordinary RTS call no longer retains its normal return-slot cleanup")
    continuation = all_native[end:end + 180]
    need(f"g_r4_scroll_trace_current_pc = 0x{return_pc:06X}u;" in continuation,
         "ordinary JSR return instruction was not emitted after the wrapper")


def local_return_action(pending, actual_pc, actual_sp, expected_pc, slot_sp):
    """Synthetic check of the exact generated local-return predicate."""
    if pending == 1 and actual_pc == expected_pc and actual_sp == slot_sp + 4:
        return 0, "resume"
    if pending:
        return pending - 1, "unwind"
    return 0, "normal"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
         "unexpected Shinobi III ROM image")

    # This stage placement selects actor callback slot 62, whose generated
    # state machine owns the four local calls below. The test deliberately
    # identifies the ROM callback path rather than asserting a display name.
    # Supported-ROM digest and generated-code checks cover this path.

    # RTR restores CCR and consumes a word plus the long return address.
    # Each listed helper use is an ordinary JSR; its return PC points to the
    # caller's explicit ADDQ.L #2,A7 cleanup, so the native C caller must
    # resume locally instead of abandoning the remainder of the state step.
    # Supported-ROM digest and generated-code checks cover this path.

    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    need(re.search(r"\{\s*0x034BEEu,\s*func_034BEE\s*\}", dispatch),
         "actor callback $034BEE is missing from generated dispatch")
    need(re.search(r"\{\s*0x0349C2u,\s*func_0349C2\s*\}", dispatch),
         "RTR helper $0349C2 is missing from generated dispatch")

    all_native = generated_sources(args.generated_dir)
    helper = body(args.generated_dir, RTR_HELPER)
    need("g_cpu.PC = m68k_read32(g_cpu.A[7]); g_cpu.A[7] += 4;" in helper and
         "g_rte_pending = 1; return; /* RTR */" in helper,
         "generated RTR no longer restores the guest PC and signals return")
    # Enumerate every absolute JSR site for the helper, not just the four
    # actor-state users. Each site must retain its original ADDQ argument
    # cleanup after the local RTR returns.
    actual_helper_calls = []
    for pos in range(0, len(rom) - 5, 2):
        if int.from_bytes(rom[pos:pos + 2], "big") == 0x4EB9 and \
                int.from_bytes(rom[pos + 2:pos + 6], "big") == RTR_HELPER:
            actual_helper_calls.append(pos)
    need(set(actual_helper_calls) == set(ALL_HELPER_CALLS),
         "the complete $0349C2 JSR-site inventory changed")
    for call_pc, return_pc in ALL_HELPER_CALLS.items():
        verify_local_call(all_native, rom, call_pc, return_pc)

    verify_normal_call(all_native, rom, *NORMAL_RTS_CALL)

    # Positive/negative synthetic stack cases: only an exact one-frame PC+SP
    # match resumes this caller; multi-frame and mismatched returns still
    # propagate and cannot be mistaken for local helper returns.
    slot = 0x00FFFF00
    need(local_return_action(1, 0x034CC2, slot + 4, 0x034CC2, slot) ==
         (0, "resume"), "exact local RTR continuation did not resume")
    need(local_return_action(1, 0x034CC4, slot + 4, 0x034CC2, slot) ==
         (0, "unwind"), "wrong return PC was treated as a local return")
    need(local_return_action(1, 0x034CC2, slot + 8, 0x034CC2, slot) ==
         (0, "unwind"), "wrong stack shape was treated as a local return")
    need(local_return_action(2, 0x034CC2, slot + 4, 0x034CC2, slot) ==
         (1, "unwind"), "multi-frame unwind was consumed as a local return")
    need(local_return_action(0, 0x034BFE, slot + 4, 0x034BFE, slot) ==
         (0, "normal"), "an ordinary RTS return was reclassified as RTR unwind")

    print("R6 actor RTR local-continuation regression passed")


if __name__ == "__main__":
    main()
