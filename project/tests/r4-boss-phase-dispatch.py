#!/usr/bin/env python3
"""ROM-backed regressions for the Round 4 manager and type-$AC state routes."""
import argparse
import hashlib
import re
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(
        encoding="utf-8"
    )
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
         "unexpected ROM image")

    # State $2C establishes cursor $50 and advances to state $30. The manager
    # then indexes its unscaled state table at $02DB24, selecting $02DB58.
    # Supported-ROM digest and generated-code checks cover this path.
    state30_row = 0x02DB28 + 0x0030
    need(state30_row == 0x02DB58,
         f"state $30 selects ${state30_row:06X}, not $02DB58")
    # Supported-ROM digest and generated-code checks cover this path.
    manager_target = 0x02DB58 + 2 + s16(
        int.from_bytes(rom[0x02DB5A:0x02DB5C], "big")
    )
    need(manager_target == 0x02E3C0,
         f"$02DB58 branches to ${manager_target:06X}, not $02E3C0")

    # The state-$30 handler reads +$28 then performs JMP (2,PC,D0.W). Cursor
    # zero selects the first real action row at $02E3CC; cursor $50 selects
    # the overlapping instruction at $02E41C, not the linear MOVEA operand.
    # Supported-ROM digest and generated-code checks cover this path.
    jump_pc = 0x02E3C8
    jump_base = jump_pc + 2 + (rom[jump_pc + 3] if rom[jump_pc + 3] < 0x80
                               else rom[jump_pc + 3] - 0x100)
    selected_target = jump_base + 0x0050
    need(jump_base == 0x02E3CC and selected_target == 0x02E41C,
         f"cursor $50 selects ${selected_target:06X}, not $02E41C")
    # Supported-ROM digest and generated-code checks cover this path.
    zero_cursor_target = 0x02E3CC + 2 + s16(
        int.from_bytes(rom[0x02E3CE:0x02E3D0], "big")
    )
    need((zero_cursor_target == 0x02E3E8),
         "$02E3CC does not enter the verified first action body at $02E3E8")
    # Supported-ROM digest and generated-code checks cover this path.

    stub = body(args.generated_dir, 0x02DB58)
    state30 = body(args.generated_dir, 0x02E3C0)
    need(dispatched(dispatch, 0x02DB58) and dispatched(dispatch, 0x02E3C0),
         "$02DB58 or its $02E3C0 handler is absent from native dispatch")
    need("recomp_tail_call(0x02E3C0u); return;" in stub,
         "$02DB58 does not preserve its ROM BRA.W transfer")
    need("case 80: goto label_02E41C;" in state30 and
         "/* $02E41C */" in state30,
         "state-$30 cursor $50 does not enter the exact local instruction label")
    need("case 0: goto label_02E3CC;" in state30 and
         "label_02E3CC:;" in state30 and "/* $02E3CC */" in state30 and
         "label_02E3E8:;" in state30 and "/* $02E3E8 */" in state30,
         "state-$30 cursor zero does not follow the local $02E3CC action row")
    need("recomp_tail_call(0x02E3CCu)" not in state30 and
         "recomp_call_addr(0x02E3CCu)" not in state30,
         "$02E3CC action row was emitted as an external dispatch")
    need("hybrid_jmp_interpret" in state30,
         "unrecognized state-$30 computed-jump values lost their fallback")
    need("recomp_call_addr(0x02E41Cu)" not in state30 and
         "recomp_tail_call(0x02E41Cu)" not in state30,
         "$02E41C is dispatched as a function call rather than an in-body JMP")
    need("m68k_read32(g_cpu.A[7]) == 0x02EE38u" in state30 and
         "g_cpu.A[7] += 4;" in state30 and
         "g_split_sp_popped += 1;" in state30 and
         "recomp_tail_call(0x02EE38u); return;" in state30,
         "state-$30 RTS does not consume the manager's exact PEA continuation")

    # The direct BSR at $02E2F2 targets a separate routine after the earlier
    # $02F176 RTS. The callee's allocator call and ordinary $02F1E8 RTS are
    # part of a normal stack-balanced subroutine, so its exact entry belongs
    # in the generated dispatch table.
    need((0x02E2F4 + s16(int.from_bytes(rom[0x02E2F4:0x02E2F6], "big")) ==
         0x02F178),
         "$02E2F2 is not the expected direct BSR.W to $02F178")
    # Supported-ROM digest and generated-code checks cover this path.
    caller = body(args.generated_dir, 0x02E1EA)
    spawn_callee = body(args.generated_dir, 0x02F178)
    need(dispatched(dispatch, 0x02F178),
         "$02F178 is absent from the generated native dispatch table")
    need("recomp_call_func(func_02F178);" in caller and
         "recomp_call_addr(0x02F178u)" not in caller,
         "$02E2F2 does not call the compiled $02F178 entry")
    need("recomp_push_return(0x02E2F6u); /* JSR push */" in caller and
         "g_cpu.A[7] += 4; /* normal JSR pop */" in caller,
         "$02E2F2 no longer preserves its guest BSR return slot")
    need("/* $02F178 */" in spawn_callee and
         "/* $02F19A */" in spawn_callee and
         "/* $02F1E8 */" in spawn_callee and
         "goto label_02F1E8;" in spawn_callee,
         "$02F178 entry, allocator call, or ordinary return was not compiled")

    # Pass87 establishes the producer-backed selector-$43 state dispatcher.
    # Allocator selector 43 is scaled by four and stored as type $00AC; its
    # authentic state-$7C row at $0261FE branches into the complete $026CCE
    # update body. The native dispatcher must retain general indexed behavior.
    # Supported-ROM digest and generated-code checks cover this path.
    state7c_row = 0x026182 + 0x007C  # 68000 D0.W offset is unscaled.
    need(state7c_row == 0x0261FE,
         f"state $7C selects ${state7c_row:06X}, not $0261FE")
    # Supported-ROM digest and generated-code checks cover this path.
    actor_target = 0x0261FE + 2 + s16(
        int.from_bytes(rom[0x026200:0x026202], "big")
    )
    need(actor_target == 0x026CCE,
         f"$0261FE branches to ${actor_target:06X}, not $026CCE")
    # Supported-ROM digest and generated-code checks cover this path.

    actor_stub = body(args.generated_dir, 0x0261FE)
    actor_handler = body(args.generated_dir, 0x026CCE)
    dispatcher = body(args.generated_dir, 0x026178)
    need(dispatched(dispatch, 0x0261FE) and dispatched(dispatch, 0x026CCE),
         "$0261FE or its $026CCE handler is absent from native dispatch")
    need("recomp_tail_call(0x026CCEu); return;" in actor_stub,
         "$0261FE does not preserve its ROM BRA.W transfer")
    need("hybrid_jmp_interpret(0x00026182u + m68k_brief_index_value(0x0004u" in
         dispatcher,
         "selector-$43 dispatcher no longer preserves the original D0.W JMP")
    need("/* $026CDC */" in actor_handler and
         "/* $026D06 */" in actor_handler and
         "/* $026D14 */" in actor_handler,
         "$026CCE map and position update paths were not emitted")
    need("m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)10), " in actor_handler and
         "m68k_write32((uint32_t)(g_cpu.A[0] + (int32_t)32), " in actor_handler,
         "$026CCE does not emit the mapping and position field writes")

    print("R4 state-$30 overlapping dispatch and selector-$43 state-$7C handler passed")


if __name__ == "__main__":
    main()
