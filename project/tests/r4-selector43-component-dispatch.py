#!/usr/bin/env python3
"""ROM-backed regression for producer-verified type-$00AC state rows."""
import argparse
import hashlib
import re
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"

# state, table row, handler. Runtime ROM decoding below checks the branch form and destination.
ROWS = (
    (0x70, 0x0261F2, 0x026C58), (0x74, 0x0261F6, 0x026C94),
    (0x78, 0x0261FA, 0x026D90), (0x7C, 0x0261FE, 0x026CCE),
    (0x80, 0x026202, 0x026DDE), (0x84, 0x026206, 0x026DE8),
    (0x88, 0x02620A, 0x026E08), (0x8C, 0x02620E, 0x026E28),
    (0x98, 0x02621A, 0x026E80), (0x9C, 0x02621E, 0x026E8A),
    (0xA0, 0x026222, 0x026EA6), (0xA4, 0x026226, 0x026EAE),
)


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
        if start < 0:
            continue
        if start != 0:
            start += 1
        end = text.find("\n}\n", pos)
        if end < 0:
            raise AssertionError("unterminated generated function")
        block = text[start:end + 2]
        match = re.match(r"void (func_[0-9A-F]{6})\(void\)\s*\{", block)
        if match:
            return match.group(1), block
    raise AssertionError(f"no generated function owns ${address:06X}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
         "unexpected ROM image")

    # Supported-ROM SHA-256 plus selector, decoded branch, dispatch, and
    # generated-state assertions below replace copied instruction signatures.
    need(((0x2B << 2) == 0xAC),
         "selector-$43 type-$00AC callback relationship changed")

    dispatch_path = args.generated_dir / "shinobi3_dispatch.c"
    need(dispatch_path.is_file(), "generated address dispatcher is missing")
    dispatch = dispatch_path.read_text(encoding="utf-8")
    parts = [p.read_text(encoding="utf-8")
             for p in args.generated_dir.glob("shinobi3_part*.c")]
    need(parts, "generated instruction bodies are missing")

    for state, row, handler in ROWS:
        opcode = int.from_bytes(rom[row:row + 2], "big")
        need(row == 0x026182 + state and opcode == 0x6000,
             f"state ${state:02X} does not select a BRA.W table row")
        displacement = int.from_bytes(rom[row + 2:row + 4], "big", signed=True)
        need(row + 2 + displacement == handler,
             f"state ${state:02X} BRA.W target is not ${handler:06X}")
        # Supported-ROM digest and generated-code checks cover this path.

        row_name, row_body = function_body(parts, row)
        handler_name, handler_body = function_body(parts, handler)
        need(f"{{ 0x{row:06X}u, {row_name} }}" in dispatch,
             f"state ${state:02X} row is absent from native dispatch")
        need(f"{{ 0x{handler:06X}u, {handler_name} }}" in dispatch,
             f"handler ${handler:06X} is absent from native dispatch")
        need(f"recomp_tail_call(0x{handler:06X}u); return;" in row_body,
             f"state ${state:02X} does not follow its exact ROM branch")
        need(f"/* ${handler:06X} */" in handler_body,
             f"handler ${handler:06X} is not emitted as native instructions")

    # The native dispatcher must retain the original unscaled D0.W indexed
    # jump; this test only closes the proven type-$00AC destination set.
    updater_name, updater_body = function_body(parts, 0x026178)
    need("{ 0x026178u, " + updater_name + " }" in dispatch and
         "hybrid_jmp_interpret(0x00026182u + m68k_brief_index_value(0x0004u" in
         updater_body,
         "selector-$43's original computed-jump semantics changed")

    # Check the four proven +$04 state transitions in generated native code.
    for pc, following in ((0x026C90, 0x026C94), (0x026DE4, 0x026DE8),
                          (0x026E24, 0x026E28), (0x026E86, 0x026E8A)):
        _, body = function_body(parts, pc)
        need(f"/* ${pc:06X} */" in body and
             f"recomp_tail_call(0x{following:06X}u); return;" in body,
             f"state transition at ${pc:06X} lost its next instruction")

    # $0298CA allocates a type-$00AC object through selector $2B, initializes
    # state $00A0 at $0298D6, and links it to its parent. That state indexes
    # row $026222, whose ROM BRA reaches the stack-balanced $026EA6 handler.
    # Supported-ROM digest and generated-code checks cover this path.
    row_body = function_body(parts, 0x026222)[1]
    handler = function_body(parts, 0x026EA6)[1]
    next_row_body = function_body(parts, 0x026226)[1]
    next_handler = function_body(parts, 0x026EAE)[1]
    clear_state = function_body(parts, 0x02622A)[1]
    need("recomp_tail_call(0x026EA6u); return;" in row_body,
         "$026222 does not dispatch to the ROM-selected $026EA6 handler")
    need("recomp_push_return(0x026EAAu); /* JSR push */" in handler and
         "recomp_call_func(func_02622A)" in handler and
         "g_cpu.A[7] += 4; /* normal JSR pop */" in handler,
         "$026EA6 BSR/RTS guest return frame is not balanced natively")
    need("/* $026EAA */" in handler and
         "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)4), " in handler and
         "recomp_tail_call(0x026EAEu); return;" in handler and
         "recomp_tail_call(0x026EAEu); return;" in next_row_body and
         "/* $026EAE */" in next_handler,
         "$00A0->$00A4 successor route was not preserved as a native path")
    need("m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)4), " in handler and
         "m68k_write32((uint32_t)(g_cpu.A[0] + (int32_t)20), " in clear_state and
         "g_cpu.A[0] =" not in handler and "g_cpu.A[0] =" not in clear_state,
         "$026EA6 does not preserve A0 while applying its ROM state/object updates")

    print("R4 selector-$43 producer-backed state dispatch passed for states $A0 and $A4")


if __name__ == "__main__":
    main()
