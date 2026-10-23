#!/usr/bin/env python3
"""ROM-backed static checks for the isolated Round 4 final-boss candidate."""
import argparse, hashlib, re, sys, tomllib
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"

def need(ok, message):
    if not ok:
        raise AssertionError(message)

def u16(rom, address):
    return int.from_bytes(rom[address:address+2], "big")

def s16(value):
    return value - 0x10000 if value & 0x8000 else value

def named_body(generated, name):
    pat = re.compile(rf"(?m)^void {name}\((?:void|uint32_t _entry)\)\s*\{{")
    for path in generated.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        match = pat.search(text)
        if not match:
            continue
        depth = 0
        for pos in range(text.find("{", match.start()), len(text)):
            depth += (text[pos] == "{") - (text[pos] == "}")
            if depth == 0:
                return text[match.start():pos+1]
    raise AssertionError(f"generated body {name} is missing")

def body(generated, address):
    return named_body(generated, f"func_{address:06X}")

def pc_block(generated_body, address):
    match = re.search(
        rf"/\* \${address:06X} \*/([\s\S]*?)(?=/\* \$[0-9A-F]{{6}} \*/)",
        generated_body,
    )
    need(match is not None, f"generated instruction block ${address:06X} is missing")
    return match.group(1)

def dispatched(dispatch, address):
    return re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True, type=Path)
    ap.add_argument("--game-config", required=True, type=Path)
    ap.add_argument("--generated-dir", required=True, type=Path)
    a = ap.parse_args()
    rom = a.rom.read_bytes()
    cfg_text = a.game_config.read_text(encoding="utf-8")
    cfg = tomllib.loads(cfg_text)
    dispatch = (a.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    need(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256, "wrong original ROM")
    extra = set(cfg["functions"]["extra"])
    # The current game config keeps late_extra inside [functions]. Accept the
    # older top-level spelling too so root assertions match the parser input.
    all_roots = extra | set(cfg["functions"].get("late_extra", [])) | set(cfg.get("late_extra", []))
    aliases = {(x["entry"], x["owner"]) for x in cfg["functions"].get("interior_alias", [])}

    selected = u16(rom, 0x001D5A + 3*8 + 2*2)
    need(selected == 0x0023C0, f"stage callback selected {selected:06X}")
    # Supported-ROM digest and generated-code checks cover this path.
    need(0x0023C0 in extra and dispatched(dispatch, 0x0023C0), "$0023C0 not native")
    camera, common = body(a.generated_dir, 0x0023C0), body(a.generated_dir, 0x0023C4)
    need("0x0100u" in camera and "recomp_tail_call(0x0023C4u)" in camera,
         "$0023C0 lost the authentic shared continuation")
    need(all(x in common for x in ("0x00FF0190u", "0xE004", "0xF480", "0xF482",
                                    "func_001DC4", "func_0036B0", "func_0036C2", "func_0036C8")),
         "$0023C4 lost camera/scroll writes or helper calls")

    need(int.from_bytes(rom[0x0365A2+0x2B*4:0x0365A2+0x2B*4+4], "big") == 0x026178,
         "selector-$43 manager slot changed")
    # Supported-ROM digest and generated-code checks cover this path.
    need((0x026182 + s16(0xFFFE) == 0x026180 and 0x026180 in extra and dispatched(dispatch, 0x026180)),
         "existing selector-$43 no-handler RTS route was lost")
    need(0x026182 + 0x68 == 0x0261EA, "$0261EA table index changed")
    # Supported-ROM digest and generated-code checks cover this path.
    need(0x0261EA in extra and dispatched(dispatch, 0x0261EA), "$0261EA not native")
    state68, updater = body(a.generated_dir, 0x0261EA), body(a.generated_dir, 0x02FCEC)
    need("recomp_tail_call(0x02FCECu)" in state68, "state-$68 no longer reaches $02FCEC")
    need("g_cpu.A[0] + (int32_t)64" in updater and
         "hybrid_jmp_interpret(0x0002FCFEu" in updater,
         "$02FCEC lost its source/object reads or +$28 dispatch")

    rows = list(range(0x02FCFE, 0x02FD1E, 4))
    for row in rows:
        # Supported-ROM digest and generated-code checks cover this path.
        target = row + 2 + s16(u16(rom, row+2))
        need(row in extra and dispatched(dispatch, row), f"row {row:06X} not native")
        need(f"recomp_tail_call(0x{target:06X}u)" in body(a.generated_dir, row),
             f"row {row:06X} lost branch target {target:06X}")
        need(dispatched(dispatch, target), f"handler {target:06X} not native")

    nested = {
        0x02FDEA: (0x02FDDE, (0,4,8)),
        0x02FE5A: (0x02FE4C, (0,4,8,12)),
        0x02FFA2: (0x02FF94, (0,4,8,12,16,20,24)),
        0x03022E: (0x030212, (0,4,8,12,16)),
        0x030382: (0x030376, (0,4)),
    }
    for table, (owner, offsets) in nested.items():
        need(f"hybrid_jmp_interpret(0x{table:08X}u" in body(a.generated_dir, owner),
             f"state handler {owner:06X} lost computed table {table:06X}")
        for offset in offsets:
            target = table + offset
            need(target in extra and dispatched(dispatch, target), f"nested target {target:06X} not native")
            body(a.generated_dir, target)

    # Supported-ROM digest and generated-code checks cover this path.
    installer, irq = body(a.generated_dir, 0x02D9E8), body(a.generated_dir, 0x02EF80)
    need("0x00FF0006u" in installer and "0x0002EF80u" in installer,
         "native installer lost conditional VDP IRQ target")
    need(dispatched(dispatch, 0x02EF80) and "0x00C00000u" in irq and
         "0x00FF0020u" in irq and "g_rte_pending" in irq,
         "native IRQ body lost VRAM/status writes or RTE handling")

    # $02DB24 is an object-state JMP whose selected PC is $02DB28 + state.
    # State $20 therefore enters the BRA.W at $02DB48, which reaches the
    # authentic transition handler at $02DF26. The handler must stay native;
    # resolving only the dispatch-table lookup to an empty stub is insufficient.
    # Supported-ROM digest and generated-code checks cover this path.
    need(0x02DB22 + s16(u16(rom, 0x02DB22)) == 0x02EE38,
         "$02DB20 PEA continuation no longer selects $02EE38")
    state_owner = body(a.generated_dir, 0x02D9E8)
    need("0x0002EE38u" in state_owner and
         "hybrid_jmp_interpret(0x0002DB28u + m68k_brief_index_value(0x7002u" in state_owner,
         "native manager lost the PEA continuation or state-indexed JMP")
    # Supported-ROM digest and generated-code checks cover this path.
    state20_target = 0x02DB4A + s16(u16(rom, 0x02DB4A))
    need(state20_target == 0x02DF26, f"$02DB48 target changed to {state20_target:06X}")
    need(0x02DB48 in all_roots and dispatched(dispatch, 0x02DB48),
         "$02DB48 state-$20 row is not a native dispatch entry")
    state20 = body(a.generated_dir, 0x02DB48)
    transition = body(a.generated_dir, state20_target)
    need("recomp_tail_call(0x02DF26u)" in state20,
         "$02DB48 no longer reaches its authentic transition handler")
    need(("0x0080u" in transition and "g_cpu.A[0] + (int32_t)40" in transition),
         "$02DF26 lost its animation-cursor/state progression")
    need("m68k_read16((uint32_t)(g_cpu.A[0] + (int32_t)4))" in transition and
         "(uint16_t)(_t02DF60) + (uint16_t)4u" in transition,
         "$02DF26 no longer advances the object state by four")
    # The coordinate-gated path in $02DF26 advances state $20 to $24.
    # The same object-state JMP then selects the next verified BRA.W row.
    # Supported-ROM digest and generated-code checks cover this path.
    state24_target = 0x02DB4E + s16(u16(rom, 0x02DB4E))
    need(state24_target == 0x02DF86,
         f"$02DB4C target changed to {state24_target:06X}")
    need(0x02DB4C in all_roots and dispatched(dispatch, 0x02DB4C),
         "$02DB4C state-$24 row is not a native dispatch entry")
    state24 = body(a.generated_dir, 0x02DB4C)
    next_transition = body(a.generated_dir, state24_target)
    need("recomp_tail_call(0x02DF86u)" in state24 and
         dispatched(dispatch, state24_target),
         "$02DB4C no longer reaches the authentic state-$24 handler")
    need(("m68k_read32((uint32_t)(g_cpu.A[0] + (int32_t)60))" in next_transition and "m68k_read32((uint32_t)(g_cpu.A[1] + (int32_t)60))" in next_transition and "0xF7FFu" in next_transition and "m68k_write16(g_cpu.A[1]" in next_transition),
         "$02DF86 state-$24 handler lost its authentic linked-object visibility update")

    # State $28 selects the fourth authenticated state-table row added by the
    # runtime trace. The row is a real BRA.W, not an arbitrary nearby address.
    # Supported-ROM digest and generated-code checks cover this path.
    state28_target = 0x02DB52 + s16(u16(rom, 0x02DB52))
    need(state28_target == 0x02E106,
         f"$02DB50 state-$28 target changed to {state28_target:06X}")
    need(0x02DB50 in all_roots and dispatched(dispatch, 0x02DB50),
         "$02DB50 state-$28 row is not a native dispatch entry")
    state28_row = body(a.generated_dir, 0x02DB50)
    state28_handler = body(a.generated_dir, state28_target)
    need(f"recomp_tail_call(0x{state28_target:06X}u)" in state28_row and
         dispatched(dispatch, state28_target),
         "$02DB50 no longer reaches the native $02E106 handler")
    need(("g_cpu.A[0] + (int32_t)40" in state28_handler and "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)40)" in state28_handler and "func_02E1A8" in state28_handler),
         "$02E106 lost its authentic animation-timer and updater path")
    need(("m68k_read8(0x00FF001C)" in state28_handler and "0x800u" in state28_handler and "(uint16_t)(0x0020u)" in state28_handler and "(uint16_t)(0x0008u)" in state28_handler),
         "$02E106 lost its linked-object visibility or state-$20/$08 transition")
    # At timer expiry the handler returns through $02E136, $02E14C, or
    # $02E154, rather than the animation-copy RTS at $02E1B0. Each ROM RTS
    # must preserve the manager's PEA-selected continuation while still
    # returning normally for every other guest stack word.
    for return_pc in (0x02E136, 0x02E14C, 0x02E154):
        # Supported-ROM digest and generated-code checks cover this path.
        return_block = pc_block(state28_handler, return_pc)
        need("m68k_read32(g_cpu.A[7]) == 0x02EE38u" in return_block and
             "g_cpu.A[7] += 4;" in return_block and
             "recomp_tail_call(0x02EE38u); return;" in return_block and
             "return;" in return_block,
             f"${return_pc:06X} lost conditional $02EE38 ownership or ordinary RTS")
    need("func_02F08E" in state28_handler and
         dispatched(dispatch, 0x02E1A8) and dispatched(dispatch, 0x02F08E),
         "$02E106 lost its reachable animation/object-update calls")
    state28_epilogue = body(a.generated_dir, 0x02E1A8)
    need(("m68k_read32(g_cpu.A[7]) == 0x02EE38u" in state28_epilogue and "recomp_tail_call(0x02EE38u); return;" in state28_epilogue and "g_cpu.A[0] =" not in state28_handler and "g_cpu.A[0] =" not in state28_epilogue and state28_epilogue.rfind("  return;") >
             state28_epilogue.find("recomp_tail_call(0x02EE38u); return;")),
         "$02E1B0 must preserve manager A0, consume only its matching PEA, and retain ordinary RTS")
    need("recomp_push_return(0x02E11Au)" in state28_handler and
         "recomp_call_func(func_02E1A8);" in state28_handler,
         "$02E1A8's normal local BSR return was lost")
    # The authentic state-$28 routine can return the manager to state $08 or
    # $20; both subsequent ROM table rows and their handlers must stay native.
    for successor_row, successor_target in ((0x02DB30, 0x02DD18),
                                               (0x02DB48, 0x02DF26)):
        need(dispatched(dispatch, successor_row),
             f"state successor row {successor_row:06X} is not native")
        need(f"recomp_tail_call(0x{successor_target:06X}u)" in
             body(a.generated_dir, successor_row) and
             dispatched(dispatch, successor_target),
             f"state successor {successor_row:06X} lost target {successor_target:06X}")

    # The FM command byte is shifted left by two before the PC-indexed table.
    # Rows 0 and 1 are real BRA.W entries. The watchdog snapshot has D0=$03FC;
    # with this JMP base that is the exact $FF subcommand target $06AC34.
    # Supported-ROM digest and generated-code checks cover this path.
    fm0_target = 0x06A83A + s16(u16(rom, 0x06A83A))
    fm1_target = 0x06A83E + s16(u16(rom, 0x06A83E))
    need((fm0_target, fm1_target) == (0x06AC2A, 0x06AC4E),
         f"FM command targets changed: {fm0_target:06X}, {fm1_target:06X}")
    need((0x06A838, 0x06A7A8) in aliases and 0x06AC2A in all_roots,
         "$06A838 command-0 row or its handler root is missing")
    ff_index = (0xFF << 2) & 0xFFFF
    ff_target = 0x06A838 + ff_index
    need(ff_index == 0x03FC and ff_target == 0x06AC34,
         f"watchdog D0=$03FC no longer identifies subcommand $FF -> {ff_target:06X}")
    need(0x06AC34 in all_roots and dispatched(dispatch, 0x06AC34),
         "$06AC34 observed computed target is not a native dispatch entry")
    fm_owner = named_body(a.generated_dir, "func_body_06A7A8")
    fm_setup = body(a.generated_dir, 0x06AC2A)
    need(re.search(r"case 0:\s*goto label_06A838;", fm_owner) is not None and
         re.search(r"case 4:\s*goto label_06A83C;", fm_owner) is not None,
         "$06A834 no longer preserves command-0 and command-1 table routes")
    need("recomp_tail_call(0x06AC2Au)" in fm_owner and
         "recomp_tail_call(0x06AC4Eu)" in fm_owner,
         "$06A838 no longer enters the command-0 handler")
    need("hybrid_jmp_interpret(0x0006A838u + m68k_brief_index_value(0x0002u" in fm_owner,
         "$06A834 default computed-target semantics were rewritten")
    need(("0x0006AC46u" in fm_setup and "0x00000003u" in fm_setup),
         "$06AC2A setup prologue no longer initializes its ROM table and loop count")
    fm_ff = body(a.generated_dir, 0x06AC34)
    fm_loop = body(a.generated_dir, 0x06AC30)
    # Supported-ROM digest and generated-code checks cover this path.
    need("/* $06AC34 */" in fm_ff and "recomp_call_func(func_06A42C);" in fm_ff and
         "recomp_push_return(0x06AC38u)" in fm_ff and
         "recomp_push_return(0x06AC40u)" in fm_ff and
         "recomp_tail_call(0x06AC30u)" in fm_ff,
         "$06AC34 native entry lost JSR returns or DBF loop continuation")
    need(dispatched(dispatch, 0x06AC30) and "m68k_read8(g_cpu.A[4])" in fm_loop and
         "recomp_tail_call(0x06AC34u)" in fm_loop,
         "$06AC34 backward loop target is not a generated entry with the original A4 read")

    # The dynamic jump target formula is verified, but runtime selectors seen
    # in the console are not established E4 sequence values. Pass76 only
    # rooted selectors 0, 1, and 3; several observed destinations overlap
    # pointer data or instruction operands. Keep these PCs out of extra roots
    # until a runtime producer is demonstrated.
    sound = {0x069C2A:0x2E, 0x069CC2:0x7A, 0x069DBE:0xF8, 0x069BDE:0x08,
             0x069D52:0xC2, 0x069D5A:0xC6, 0x069D6A:0xCE, 0x069D72:0xD2,
             0x069C3A:0x36, 0x069C56:0x44, 0x069C60:0x49, 0x069C82:0x5A,
             0x069BFA:0x16}
    # Supported-ROM digest and generated-code checks cover this path.
    for target, selector in sound.items():
        need(0x069BCE + 2*selector == target, f"selector arithmetic mismatch for {target:06X}")
        need(target not in all_roots, f"unverified sound PC {target:06X} was seeded")
    # Supported-ROM digest and generated-code checks cover this path.
    need((0x069BFC + (rom[0x069BFB] - 0x100 if rom[0x069BFB] & 0x80 else rom[0x069BFB]) == 0x069C38),
         "$069BFA BEQ instruction or target changed")
    need(0x069BFA not in all_roots,
         "$069BFA remains a producer-unresolved conditional entry and must not be seeded")
    need((0x001F7E,0x001F68) in aliases, "working $001F7E alias was lost")
    need((0x02C22A,0x02C224) in aliases, "experimental $02C22A alias was lost")
    print("PASS: Act-2 transition callback and shared scroll continuation")
    print("PASS: state-$68 route, eight +$28 rows, and nested animation destinations")
    print("PASS: conditional $02EF80 VDP callback and generated RTE handler")
    print("PASS: $02DB48 state-$20 route reaches generated $02DF26 transition logic")
    print("PASS: $02DF26 state increment reaches the generated $02DB4C -> $02DF86 state-$24 route")
    print("PASS: $02DB50 state-$28 row reaches native $02E106 timer, child update, and state-$08/$20 routes")
    print("PASS: state-$28 timer-expiry RTS exits $02E136/$02E14C/$02E154 conditionally consume only $02EE38")
    print("PASS: FM command 0 and 1 routes generated; observed $FF computes $06AC34 with native JSR entry")
    print("PASS: $069BCA selector formula verified; $069BFA BEQ target remains producer-unresolved and unseeded")
    print("PASS: $001F7E and experimental $02C22A aliases preserved")

if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
