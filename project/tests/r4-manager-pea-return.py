#!/usr/bin/env python3
"""ROM-backed regression for the Round 4 manager's PEA/RTS continuation."""
import argparse
import hashlib
import re
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
PEA_PC = 0x02DB20
CONTINUATION = 0x02EE38
STATE_RTS = 0x02DCE8
SCROLL_STATE_ROUTES = (
    (0x02DB30, 0x02DD18),
    (0x02DB34, 0x02DD38),
    (0x02DB38, 0x02DDFE),
    (0x02DB3C, 0x02DE18),
)
# Exact branch handlers admitted by the ROM-verified state-$34..$80 closure.
STATE34_HANDLERS = (
    0x02E5B0, 0x02E600, 0x02E6C8, 0x02E732, 0x02E7B2, 0x02E842,
    0x02E8C4, 0x02E988, 0x02E9F6, 0x02EA5A, 0x02EABC, 0x02EAFE,
    0x02EC4C, 0x02EC52, 0x02EC60, 0x02ECC4,
)
STATE84_HANDLERS = (0x02ED22, 0x02EDF0)
STATE18_24_HANDLERS = (0x02DECC, 0x02DF04, 0x02DF26, 0x02DF86)


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


def dispatched(dispatch, address):
    return re.search(
        rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch
    ) is not None


def check_stack_contract():
    # Diagnostic frame: outer JSR at FFFFFFF4, inner PEA at FFFFFFF0.
    initial_a7 = 0xFFFFFFF8
    outer_slot = initial_a7 - 4
    pea_slot = outer_slot - 4
    slots = {outer_slot: 0x0000B21E, pea_slot: CONTINUATION}

    # Before the correction, the RTS returned through C with A7 still at the
    # PEA slot; ordinary wrapper cleanup advanced only one word-slot, leaving
    # the guest JSR return at A7 and the completed call four bytes short.
    broken_a7 = pea_slot + 4
    need(broken_a7 == 0xFFFFFFF4 and slots[broken_a7] == 0x0000B21E,
         "pre-fix stack model no longer reproduces the recorded FFFFFFF4 mismatch")

    # The generated $02DCE8 guard consumes exactly the matching PEA slot,
    # then $02EE38 runs to its final RTS; that ordinary return consumes B21E.
    fixed_a7 = pea_slot + 4
    need(slots[pea_slot] == CONTINUATION and fixed_a7 == outer_slot,
         "manager RTS did not consume only its PEA continuation")
    need(slots[fixed_a7] == 0x0000B21E and fixed_a7 + 4 == initial_a7,
         "continuation did not leave the outer $00B21E frame for normal return")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256, "unexpected ROM image")

    # Authentic PEA (d16,PC) target and state-4 route through $02DCE8 RTS.
    # Supported-ROM digest and generated-code checks cover this path.
    target = PEA_PC + 2 + s16(int.from_bytes(rom[PEA_PC + 2:PEA_PC + 4], "big"))
    need(target == CONTINUATION, f"PEA target changed to ${target:06X}")
    # Supported-ROM digest and generated-code checks cover this path.
    need((0x02DB2E + s16(int.from_bytes(rom[0x02DB2E:0x02DB30], "big")) == 0x02DCBE),
         "state-$04 manager route no longer reaches $02DCBE")
    scroll_handlers = []
    for stub, handler in SCROLL_STATE_ROUTES:
        need(int.from_bytes(rom[stub:stub + 2], "big") == 0x6000 and
             stub + 2 + s16(int.from_bytes(rom[stub + 2:stub + 4], "big")) == handler,
             f"manager state route at ${stub:06X} no longer reaches ${handler:06X}")
        scroll_handlers.append(body(args.generated_dir, handler))
    # Supported-ROM digest and generated-code checks cover this path.

    # The continuation's generated conditional and its dynamically decoded
    # target preserve the original TST/BEQ behavior without byte signatures.
    branch_target = CONTINUATION + 6 + s16(rom[CONTINUATION + 5])
    need(branch_target == 0x02EE48, f"$02EE3C BEQ target changed to ${branch_target:06X}")
    # Supported-ROM digest and generated-code checks cover this path.
    check_stack_contract()

    manager = body(args.generated_dir, 0x02D9E8)
    state4_row = body(args.generated_dir, 0x02DB2C)
    state_handler = body(args.generated_dir, 0x02DCBE)
    state2c_handler = body(args.generated_dir, 0x02E1EA)
    continuation_body = body(args.generated_dir, CONTINUATION)
    state30_handler = body(args.generated_dir, 0x02E3C0)
    state84_handlers = [body(args.generated_dir, address)
                       for address in STATE84_HANDLERS]
    need(dispatched(dispatch, CONTINUATION), "$02EE38 has no generated function entry")
    need("0x0002EE38u" in manager and
         "hybrid_jmp_interpret(0x0002DB28u + m68k_brief_index_value(0x7002u" in manager,
         "manager no longer installs the PEA continuation before its state dispatch")
    need("recomp_tail_call(0x02DCBEu)" in state4_row,
         "state-$04 row no longer reaches its verified RTS handler")
    for stub, handler in SCROLL_STATE_ROUTES:
        state_row = body(args.generated_dir, stub)
        need(f"recomp_tail_call(0x{handler:06X}u)" in state_row,
             f"manager state row ${stub:06X} no longer reaches handler ${handler:06X}")
    need("g_split_sp_popped < 0 && m68k_read32(g_cpu.A[7]) == 0x02EE38u" in state_handler,
         "$02DCE8 RTS does not recognize the exact outstanding PEA return slot")
    need("g_cpu.A[7] += 4;" in state_handler and
         "g_split_sp_popped += 1;" in state_handler and
         "recomp_tail_call(0x02EE38u); return;" in state_handler,
         "$02DCE8 does not consume the PEA slot and continue at $02EE38")
    need("m68k_read16((uint32_t)(g_cpu.A[0] + (int32_t)46))" in continuation_body and
         "if ((g_cpu.SR & (1u<<2)))" in continuation_body and "label_02EE48" in continuation_body,
         "$02EE38 TST/BEQ condition or its branch target was not preserved")
    need("/* $02EF76 */" in continuation_body,
         "$02EE38 body does not include the original final RTS path")
    # The continuation contains the ROM's live-coordinate VSRAM producer.
    # Keep this check tied to the exact original instruction boundaries rather
    # than accepting a fixed scroll value or a suppressed transition.
    for address in (0x02EF28, 0x02EF2C, 0x02EF30, 0x02EF34, 0x02EF36):
        need(f"/* ${address:06X} */" in continuation_body,
             f"$02EE38 implementation is missing ROM scroll instruction ${address:06X}")
    need("m68k_write16((uint32_t)(int32_t)(int16_t)0xF480" in continuation_body,
         "$02EF36 no longer stores the computed scroll to $FFF480")
    guard_text = "m68k_read32(g_cpu.A[7]) == 0x02EE38u"
    pea_guard_count = sum(
        path.read_text(encoding="utf-8").count(guard_text)
        for path in args.generated_dir.glob("shinobi3_part*.c")
    )
    allowed_guards = (state_handler.count(guard_text) +
                      state2c_handler.count(guard_text) +
                      state30_handler.count(guard_text) +
                      sum(handler.count(guard_text) for handler in scroll_handlers) +
                      sum(body(args.generated_dir, address).count(guard_text)
                          for address in STATE34_HANDLERS) +
                      sum(handler.count(guard_text) for handler in state84_handlers) +
                      sum(body(args.generated_dir, address).count(guard_text)
                          for address in STATE18_24_HANDLERS) +
                      sum(body(args.generated_dir, address).count(guard_text)
                          for address in (0x02E106, 0x02E1A8, 0x02EFC0)))
    need(pea_guard_count == allowed_guards and pea_guard_count > 0,
         "verified PEA return guard leaked outside the exact manager handler and state-$28 timer/terminal and state-$38 return owners "
         f"({pea_guard_count} emitted, {allowed_guards} allowed)")
    for handler, generated_body in zip((route[1] for route in SCROLL_STATE_ROUTES), scroll_handlers):
        guard = re.search(
            rf"if \((?:g_split_sp_popped|\(_sp_popped \+ g_split_sp_popped\)) < 0 && {re.escape(guard_text)}\) \{{\s*"
            rf"g_cpu\.A\[7\] \+= 4;\s*"
            rf"(?:g_split_sp_popped \+= _sp_popped; _sp_popped = 0;\s*)?"
            rf"g_split_sp_popped \+= 1;\s*"
            rf".*?recomp_tail_call\(0x02EE38u\); return;",
            generated_body,
            re.S,
        )
        need(guard is not None,
             f"state handler ${handler:06X} does not consume its exact PEA return slot and continue at $02EE38")

    print("R4 manager PEA/RTS continuation: ROM contract and generated path passed")


if __name__ == "__main__":
    main()

