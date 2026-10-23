#!/usr/bin/env python3
"""ROM-backed regression for state-$18/$20/$24 PEA scroll continuation."""

import argparse
import hashlib
import re
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
CONTINUATION = 0x02EE38
MANAGER_ROWS = (
    (0x02DB40, 0x02DEB4),
    (0x02DB48, 0x02DF26),
    (0x02DB4C, 0x02DF86),
)
SCROLL_HANDLERS = (0x02DECC, 0x02DF04, 0x02DF26, 0x02DF86)
RTS_SITES = {
    0x02DECC: (0x02DF02,),
    0x02DF04: (0x02DF24,),
    0x02DF26: (0x02DF74, 0x02DF84),
    0x02DF86: (0x02E020, 0x02E044, 0x02E052, 0x02E104),
}


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def s16(value):
    return value - 0x10000 if value & 0x8000 else value


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
         "unexpected Shinobi III ROM image")
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    parts = sorted(args.generated_dir.glob("shinobi3_part*.c"))
    need(parts, f"generated C parts are missing from {args.generated_dir}")
    all_native = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                            for p in parts)

    # Authenticate the manager's exact PEA and indexed state dispatch.
    # Supported-ROM digest and generated-code checks cover this path.
    pea_target = 0x02DB20 + 2 + s16(int.from_bytes(rom[0x02DB22:0x02DB24], "big"))
    need(pea_target == CONTINUATION,
         f"manager PEA now targets ${pea_target:06X}")
    # Supported-ROM digest and generated-code checks cover this path.

    # State $14 can select $18 with cursor $0200. That means the first
    # state-$18 update takes indexed row 2 ($02DEC4 -> $02DF04); cursor $0100
    # selects row 1 and cursor $0000 selects row 0. Preserve all three ROM
    # paths and the row at $02DEC2 that writes cursor $0100 before $02DECC.
    # Supported-ROM digest and generated-code checks cover this path.
    computed_rows = ((0x02DEC0, 0x02DECC),
                     (0x02DEC2, 0x02DEC6),
                     (0x02DEC4, 0x02DF04))
    for row, expected in computed_rows:
        # These are BRA.S entries in the computed table; decode the branch
        # class and signed 8-bit displacement instead of copying its bytes.
        opcode = rom[row]
        displacement = rom[row + 1]
        if displacement & 0x80:
            displacement -= 0x100
        need(opcode == 0x60 and row + 2 + displacement == expected,
             f"state-$18 indexed row ${row:06X} no longer reaches ${expected:06X}")
    # Supported-ROM digest and generated-code checks cover this path.

    # Manager state rows must remain authentic BRA.W edges to the already
    # generated state handlers; no new ROM aliases or configuration roots.
    for row, target in MANAGER_ROWS:
        need(int.from_bytes(rom[row:row + 2], "big") == 0x6000,
             f"manager row ${row:06X} is not a word-displacement branch")
        actual = row + 2 + s16(int.from_bytes(rom[row + 2:row + 4], "big"))
        need(actual == target, f"manager row ${row:06X} now targets ${actual:06X}")
        need(re.search(rf"\{{\s*0x{row:06X}u,\s*func_{row:06X}\s*\}}", dispatch),
             f"manager row ${row:06X} is missing from generated dispatch")
        need(re.search(rf"\{{\s*0x{target:06X}u,\s*func_{target:06X}\s*\}}", dispatch),
             f"manager handler ${target:06X} is missing from generated dispatch")

    # Each listed address is an authentic instruction-boundary RTS within the
    # corresponding generated body. The new native edge is conditional on
    # both outstanding PEA depth and an exact guest stack word match.
    guard = "m68k_read32(g_cpu.A[7]) == 0x02EE38u"
    for owner, rts_sites in RTS_SITES.items():
        handler = body(args.generated_dir, owner)
        need(handler.count(guard) == len(rts_sites),
             f"${owner:06X} does not have one exact-stack guard per ROM RTS")
        need(handler.count("recomp_tail_call(0x02EE38u); return;") == len(rts_sites),
             f"${owner:06X} does not dispatch every matched RTS to $02EE38")
        for rts in rts_sites:
            # Supported-ROM digest and generated-code checks cover this path.
            need(f"/* ${rts:06X} */" in handler,
                 f"generated ${owner:06X} body omits ROM RTS ${rts:06X}")
        need("g_cpu.A[7] += 4;" in handler and
             "g_split_sp_popped += 1;" in handler,
             f"${owner:06X} does not consume exactly one guest PEA slot")
        need("recomp_tail_call(0x02EE38u); return;" in handler,
             f"${owner:06X} does not resume the PEA continuation")

    # The state-$14 / state-$18 code keeps its original branches and cursor
    # side effects; only its split RTS owners gain continuation guards.
    state14 = body(args.generated_dir, 0x02DE18)
    need("/* $02DE32 */" in state14 and "/* $02DE56 */" in state14 and
         "g_cpu.D[0] = 0x00000018u;" in state14 and
         "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)4), (uint16_t)((uint16_t)g_cpu.D[0]))" in state14 and
         "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)40), (uint16_t)(0x0200u))" in state14,
         "generated state-$14 to state-$18 conditional transition was changed")
    state18 = body(args.generated_dir, 0x02DEB4)
    need("m68k_brief_index_value(0x0002u, g_cpu.D[0], g_cpu.A[0])" in state18 and
         "hybrid_jmp_interpret(0x0002DEC0u" in state18,
         "state-$18 indexed-dispatch fallback semantics changed")
    scroll = body(args.generated_dir, CONTINUATION)
    need("/* $02EF28 */" in scroll and "/* $02EF36 */" in scroll and
         "m68k_write16((uint32_t)(int32_t)(int16_t)0xF480" in scroll,
         "$02EE38 live scroll updater is missing or no longer writes FFF480")

    # A mismatched stack word must stay on the legacy RTS path. The emitted
    # guard is equality-gated; after the closing brace the normal C return
    # remains present, while a matching word consumes four bytes and tails to
    # the exact continuation. A0 and all data registers are untouched here.
    sample = body(args.generated_dir, 0x02DECC)
    guard_block = re.search(
        r"if \(g_split_sp_popped < 0 && " + re.escape(guard) +
        r"\) \{\s*g_cpu\.A\[7\] \+= 4;(?P<ops>.*?)"
        r"recomp_tail_call\(0x02EE38u\); return;\s*\}",
        sample, re.S)
    need(guard_block is not None,
         "matched PEA return does not use the exact conditional stack guard")
    need("g_split_sp_popped += 1;" in guard_block.group("ops"),
         "matched PEA return does not balance one pushed guest return slot")
    need("g_cpu.A[0]" not in guard_block.group("ops") and
         "g_cpu.D[" not in guard_block.group("ops") and
         "g_cpu.SR" not in guard_block.group("ops"),
         "continuation shim mutates guest registers or condition codes")
    need(re.search(r"recomp_tail_call\(0x02EE38u\); return;\s*\}\s*"
                   r"(?:if \(g_split_sp_popped > 0\)|g_native_insn_count\+\+)",
                   sample),
         "nonmatching stack values no longer fall through to the original RTS return")

    print("PASS: manager state-$18/$20/$24 rows and computed state-$18 routes match ROM")
    print("PASS: all eight split handler RTSs conditionally consume exact PEA $02EE38")
    print("PASS: unmatched stack values and guest registers retain the original fallback behavior")
    print("PASS: matched continuation reaches the generated live-coordinate $FFF480 updater")


if __name__ == "__main__":
    main()
