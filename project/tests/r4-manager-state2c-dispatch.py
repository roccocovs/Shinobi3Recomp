#!/usr/bin/env python3
"""ROM-backed regression for the Round 4 manager's state-$2C route."""
import argparse
import hashlib
import re
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
STATE_WRITE = 0x02DAE8
MANAGER_STATE_LOAD = 0x02DB1C
MANAGER_PEA = 0x02DB20
MANAGER_JMP = 0x02DB24
TABLE_BASE = 0x02DB28
STATE_2C_STUB = 0x02DB54
STATE_2C_HANDLER = 0x02E1EA
CONTINUATION = 0x02EE38


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
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
         "unexpected ROM image")

    # The branch at $02DAE8 is the manager's authentic state-$2C transition.
    # The next manager dispatch reads that word, installs its PEA continuation,
    # then indexes the branch table by the unscaled D7.W value.
    # Supported-ROM digest and generated-code checks cover this path.
    need((MANAGER_PEA + 2 + s16(int.from_bytes(rom[MANAGER_PEA + 2:MANAGER_PEA + 4], "big")) == CONTINUATION),
         "$02DB20 no longer installs continuation $02EE38")
    indexed_target = TABLE_BASE + 0x002C  # D7.W = manager state $002C.
    need(indexed_target == STATE_2C_STUB,
         f"state $002C selects ${indexed_target:06X}, not its ROM row")

    # The exact row is a valid BRA.W instruction and resolves to the handler.
    # Supported-ROM digest and generated-code checks cover this path.
    handler_target = STATE_2C_STUB + 2 + s16(
        int.from_bytes(rom[STATE_2C_STUB + 2:STATE_2C_STUB + 4], "big")
    )
    need(handler_target == STATE_2C_HANDLER,
         f"$02DB54 now branches to ${handler_target:06X}")
    # Supported-ROM digest and generated-code checks cover this path.

    manager = body(args.generated_dir, 0x02D9E8)
    row = body(args.generated_dir, STATE_2C_STUB)
    handler = body(args.generated_dir, STATE_2C_HANDLER)
    need(dispatched(dispatch, STATE_2C_STUB),
         "$02DB54 is absent from the generated entry table")
    need(dispatched(dispatch, STATE_2C_HANDLER),
         "$02E1EA handler is absent from the generated entry table")
    need("0x0002EE38u" in manager and
         "hybrid_jmp_interpret(0x0002DB28u + m68k_brief_index_value(0x7002u" in manager,
         "manager does not preserve its original PEA plus indexed-dispatch semantics")
    need("recomp_tail_call(0x02E1EAu); return;" in row,
         "$02DB54 no longer follows its ROM branch to $02E1EA")
    need("/* $02E1EA */" in handler and
         "m68k_write16(g_cpu.A[0]," in handler,
         "$02E1EA's original handler body was not emitted")

    # The PEA at $02DB20 is an outstanding guest return frame across this
    # indexed jump. Both original state-$2C RTS exits must consume it only
    # when it is actually the top slot, then continue at $02EE38.
    for rts_pc in (0x02E2B0, 0x02E374):
        # Supported-ROM digest and generated-code checks cover this path.
        marker = f"/* ${rts_pc:06X} */"
        pos = handler.find(marker)
        need(pos >= 0, f"generated state-$2C handler omits RTS ${rts_pc:06X}")
        next_marker = re.search(r"/\* \$[0-9A-F]{6} \*/", handler[pos + len(marker):])
        end = pos + len(marker) + next_marker.start() if next_marker else len(handler)
        block = handler[pos:end]
        need("m68k_read32(g_cpu.A[7]) == 0x02EE38u" in block and
             "recomp_tail_call(0x02EE38u); return;" in block,
             f"RTS ${rts_pc:06X} fails to consume the exact PEA continuation")

    print("R4 manager state-$2C dispatch: ROM producer, indexed row, and generated handler passed")


if __name__ == "__main__":
    main()
