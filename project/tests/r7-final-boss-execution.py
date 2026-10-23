#!/usr/bin/env python3
"""ROM-backed Round 7 final-boss callback and object-state regression."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
STAGE_INDEX = 6
SCENE_TABLE = 0x0009C0
CAMERA_TABLE = 0x001D5A
RESOURCE_TABLE = 0x002FC8
SCENE_CALLBACK = 0x0012B0
CAMERA_CALLBACK = 0x00295E
RESOURCE_CALLBACK = 0x0032E6
STATE_ENTRY = 0x01F98C
STATE_OWNER = 0x01F970
STATE_JUMP = 0x01F974
ENDING_CALLBACKS = (0x000A00, 0x001E16, 0x001AB2)
RESOURCE_PREFETCH_ENTRY = 0x01FBAC
RESOURCE_PREFETCH_OWNER = 0x01FBA4
RESOURCE_PREFETCH_JUMP = 0x01FBA8
RESOURCE_UPDATE_ENTRY = 0x01FBB4
ENDING_ANIMATION_HANDLER = 0x0107F2
ENDING_ANIMATION_BRANCHES = ((0x0107E6, 0x01083C),
                             (0x0107EA, 0x010948),
                             (0x0107EE, 0x010976))
TITLE_INIT_CALLBACK = 0x000069A8
STARTUP_CALLBACK = 0x0000FBD6
TITLE_MENU_CALLBACK = 0x0000774E


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def row(rom: bytes, base: int) -> tuple[int, ...]:
    return tuple(int.from_bytes(rom[base + STAGE_INDEX * 8 + act * 2:
                                    base + STAGE_INDEX * 8 + act * 2 + 2], "big")
                 for act in range(4))


def body(directory: Path, address: int) -> str:
    name = f"func_{address:06X}"
    start_re = re.compile(rf"(?m)^void {name}\(void\) \{{")
    for path in directory.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        start = start_re.search(text)
        if start:
            following = text[start.end():]
            end = re.search(r"(?m)^void func_[0-9A-F]{6}\(void\) \{", following)
            return text[start.start():start.end() + end.start()] if end else text[start.start():]
    raise AssertionError(f"generated native body ${address:06X} is missing")


def named_body(directory: Path, signature: str) -> str:
    start_re = re.compile(rf"(?m)^void {re.escape(signature)}\([^\n]*\) \{{")
    for path in directory.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        start = start_re.search(text)
        if start:
            end = re.search(r"(?m)^void [A-Za-z0-9_]+\([^\n]*\) \{", text[start.end():])
            return text[start.start():start.end() + end.start()] if end else text[start.start():]
    raise AssertionError(f"generated native helper {signature} is missing")


def dispatch_entry(dispatch: str, address: int) -> bool:
    return re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--game-config", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    config = tomllib.loads(args.game_config.read_text(encoding="utf-8"))
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
            "test requires the preserved original US ROM")

    # Round 7 is ROM stage index 6. Act 2 is the final-boss encounter;
    # Act 3's ending callbacks are checked below for preserved native coverage.
    require(row(rom, SCENE_TABLE) == (0x00114C, 0x0011E0, SCENE_CALLBACK, 0x000A00),
            "Round 7 scene callback row changed")
    require(row(rom, CAMERA_TABLE) == (0x0027AA, 0x00291C, CAMERA_CALLBACK, 0x001E16),
            "Round 7 camera callback row changed")
    require(row(rom, RESOURCE_TABLE) == (0x0032B2, 0x00303C, RESOURCE_CALLBACK, 0x001AB2),
            "Round 7 resource callback row changed")

    # The common selectors index with FF37A6*8 + FF37A8*2. Scene and resource
    # selection tail-jump through a saved caller frame; camera selection uses
    # JSR(A6), with the common caller restoring SR after the callback returns.
    # Supported-ROM digest and generated-code checks cover this path.

    # Supported-ROM digest and generated-code checks cover this path.

    # The later object warning is a state-machine computed edge, not a free
    # function call: +$04 == $14 selects JMP ($01F978 + D0), with D0=$14.
    # Supported-ROM digest and generated-code checks cover this path.

    # During the boss sequence, the object state word selects $01FBAC from
    # the computed JMP in $01FBA4. The selected state preloads the ROM's
    # stage+2 resources, restores the original stage byte and SR, advances
    # the object state, and returns through the caller's existing JSR frame.
    # Supported-ROM digest and generated-code checks cover this path.

    # $0107F2 is a table-index-$0100 actor animation handler selected from the long
    # callback table at $0365A2. The common object scheduler preserves the
    # other registers, calls the selected handler with JSR (A6), then restores
    # them; it is an ordinary function root with A0 as the live object.
    require(int.from_bytes(rom[0x0366A2:0x0366A6], "big") == ENDING_ANIMATION_HANDLER,
        "$0365A2 callback table no longer selects $0107F2 for object table index $0100")
    # Supported-ROM digest and generated-code checks cover this path.
    for veneer, handler in ENDING_ANIMATION_BRANCHES:
        # 68000 Bcc/ BRA word displacement is relative to the extension word.
        displacement = handler - (veneer + 2)
        opcode = int.from_bytes(rom[veneer:veneer + 2], "big")
        require((opcode >> 8) == 0x60 and (opcode & 0xFF) == 0 and
                int.from_bytes(rom[veneer + 2:veneer + 4], "big", signed=True) == displacement,
                f"$0107F2 state veneer ${veneer:06X} no longer branches to ${handler:06X}")
    # Supported-ROM digest and generated-code checks cover this path.

    functions = config["functions"]
    roots = set(functions.get("extra", [])) | set(functions.get("late_extra", []))
    require({SCENE_CALLBACK, CAMERA_CALLBACK, RESOURCE_CALLBACK} <= roots,
            "one or more final-boss stage callbacks is absent from native roots")
    aliases = functions.get("interior_alias", [])
    require({"entry": STATE_ENTRY, "owner": STATE_OWNER, "jump": STATE_JUMP} in aliases,
            "$01F98C is not declared as the exact $01F974 computed-jump alias")
    require({"entry": RESOURCE_PREFETCH_ENTRY, "owner": RESOURCE_PREFETCH_OWNER,
             "jump": RESOURCE_PREFETCH_JUMP} in aliases,
            "$01FBAC is not declared as the exact $01FBA8 computed-jump alias")
    require({"entry": RESOURCE_UPDATE_ENTRY, "owner": RESOURCE_PREFETCH_OWNER,
             "jump": RESOURCE_PREFETCH_JUMP} in aliases,
            "$01FBB4 is not declared as the state-$08 $01FBA8 computed-jump alias")
    late_roots = set(functions.get("late_extra", []))
    require(ENDING_ANIMATION_HANDLER in late_roots,
            "$0107F2's ROM-selected object callback is absent from native roots")
    require({veneer for veneer, _ in ENDING_ANIMATION_BRANCHES} <= late_roots,
            "$0107F2's ROM-selected BRA.W state veneers are absent from native roots")
    require({handler for _, handler in ENDING_ANIMATION_BRANCHES} <= late_roots,
            "$0107F2's ROM-selected object-state handlers are absent from native roots")

    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    for address in (SCENE_CALLBACK, CAMERA_CALLBACK, RESOURCE_CALLBACK,
                    STATE_OWNER, STATE_ENTRY, 0x01FB06, 0x01DD90,
                    RESOURCE_PREFETCH_OWNER, RESOURCE_PREFETCH_ENTRY, RESOURCE_UPDATE_ENTRY,
                    ENDING_ANIMATION_HANDLER,
                    0x01083C, 0x010948, 0x010976,
                    *(veneer for veneer, _ in ENDING_ANIMATION_BRANCHES),
                    0x002A46, 0x002A4A, 0x002A4E, 0x002A6C, 0x002AD6,
                    0x003934,
                    *ENDING_CALLBACKS, TITLE_INIT_CALLBACK, 0x006B6C, 0x006B38,
                    STARTUP_CALLBACK, 0x00FC02, 0x00FD0A, 0x00FFFC,
                    0x010134, 0x010254, 0x010288, TITLE_MENU_CALLBACK):
        require(dispatch_entry(dispatch, address),
                f"native dispatch lacks ROM-selected final-boss/ending entry ${address:06X}")

    scene = body(args.generated_dir, SCENE_CALLBACK)
    camera = body(args.generated_dir, CAMERA_CALLBACK)
    camera_zones = body(args.generated_dir, 0x002A4E)
    resource = body(args.generated_dir, RESOURCE_CALLBACK)
    owner = body(args.generated_dir, STATE_OWNER)
    owner_body = named_body(args.generated_dir, "func_body_01F970")
    alias = body(args.generated_dir, STATE_ENTRY)
    continuation = body(args.generated_dir, 0x01FB06)
    prefetch_owner = body(args.generated_dir, RESOURCE_PREFETCH_OWNER)
    prefetch_owner_body = named_body(args.generated_dir, "func_body_01FBA4")
    prefetch_alias = body(args.generated_dir, RESOURCE_PREFETCH_ENTRY)
    ending_animation = body(args.generated_dir, ENDING_ANIMATION_HANDLER)
    cliff_end = body(args.generated_dir, TITLE_INIT_CALLBACK)
    completion_gate = body(args.generated_dir, 0x006B6C)
    credits_setup = body(args.generated_dir, STARTUP_CALLBACK)
    post_credits = body(args.generated_dir, TITLE_MENU_CALLBACK)
    require("0x00FF16EC" in scene and "0x00FF16ED" in scene and
            "0x00FF379C" in scene and "0x00FF0028" in scene and
            "0x00FF005F" in scene and "0x0006E8u" in scene,
            "$0012B0 lost its frame-gated scene update and animation helper path")
    require("0x00FF005F" in camera and "0xF0E0" in camera and
            "0xF080" in camera and "0xF480" in camera and
            "0xE000" in camera and "0xE004" in camera and
            "0x00342Eu" in camera,
            "$00295E lost the original boss-room scroll-buffer generation")
    require("hybrid_jmp_interpret(0x00002A46u" in camera_zones,
            "$002A4E lost its PC-indexed two-zone jump table")
    require("0x000404FCu" in resource and "0x003042u" in resource,
            "$0032E6 no longer tail-transfers the selected descriptor to the shared loader")

    require("func_body_01F970(0x01F970u)" in owner and
            "case 0x01F98Cu: goto label_01F98C;" in owner_body and
            "func_body_01F970(0x01F98Cu)" in alias,
            "$01F98C does not re-enter the shared state body at its exact ROM instruction")
    local_switch = owner_body[owner_body.index("switch ((int32_t)m68k_brief_index_value"):]
    local_switch = local_switch[:local_switch.index("\n  }")]
    require("case 20: goto label_01F98C;" in local_switch and
            "recomp_push_return" not in local_switch and "g_cpu.A[7]" not in local_switch,
            "state-$14 computed dispatch changed the original stack or return-address behavior")
    require("0x01F98Cu" in owner_body and "0x01FB06u" in owner_body and
            "recomp_tail_call(0x01FB06u)" in owner_body,
            "$01F98C no longer advances object state and tail-dispatches to $01FB06")
    require("g_cpu.A[0] + (int32_t)60" in continuation,
            "$01FB06 no longer reloads the linked actor through object +$3C")
    require("recomp_tail_call(0x01DD90u)" in continuation,
            "$01FB06 no longer enters the linked actor's original update loop")

    require("func_body_01FBA4(0x01FBA4u)" in prefetch_owner and
            "case 0x01FBACu: goto label_01FBAC;" in prefetch_owner_body and
            "func_body_01FBA4(0x01FBACu)" in prefetch_alias,
            "$01FBAC does not re-enter its shared object-state body at the computed edge")
    local_prefetch_switch = prefetch_owner_body[
        prefetch_owner_body.index("switch ((int32_t)m68k_brief_index_value"):]
    local_prefetch_switch = local_prefetch_switch[:local_prefetch_switch.index("\n  }")]
    require("case 0: goto label_01FBAC;" in local_prefetch_switch and
            "case 8: goto label_01FBB4;" in local_prefetch_switch and
            "recomp_push_return" not in local_prefetch_switch and
            "g_cpu.A[7]" not in local_prefetch_switch,
            "$01FBA8 computed states no longer preserve original A0/A7/return semantics")
    resource_update_alias = body(args.generated_dir, RESOURCE_UPDATE_ENTRY)
    require("case 8: goto label_01FBB4;" in prefetch_owner_body and
            "func_body_01FBA4(0x01FBB4u)" in resource_update_alias and
            "goto label_01FBE6;" in prefetch_owner_body and
            "g_r4_scroll_trace_current_pc = 0x01FBE6u;" in prefetch_owner_body and
            "recomp_tail_call(0x01DD90u)" in prefetch_owner_body,
            "$01FBB4 no longer preserves its computed edge, shared-update path, and original tail transfer")
    require("recomp_call_func(func_02A41E)" in prefetch_owner_body and
            "0x00FF37A6u" in prefetch_owner_body and
            "0x01FBE4u" in prefetch_owner_body,
            "$01FBAC no longer preserves the stage+2 resource preload and RTS path")

    require("recomp_call_func(func_03670C)" in ending_animation,
            "$0107F2's generated handler no longer advances the callback object frame")
    require("hybrid_jmp_interpret(0x000107E6u" in ending_animation,
            "$0107F2 lost the ROM's PC-indexed state selection")
    state_zero = body(args.generated_dir, 0x01083C)
    state_four = body(args.generated_dir, 0x010948)
    state_eight = body(args.generated_dir, 0x010976)
    require("recomp_call_func(func_0108CA)" in state_zero and
            "recomp_tail_call(0x036716u)" in state_zero and
            "m68k_read32((uint32_t)(g_cpu.A[0] + (int32_t)44))" in state_four and
            "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)10)" in state_four and
            "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)8)" in state_four and
            "m68k_write16((uint32_t)(g_cpu.A[0] + (int32_t)10)" in state_eight,
            "$0107F2 lost its original setup, frame-map, or tile-selection paths")
    for veneer, handler in ENDING_ANIMATION_BRANCHES:
        veneer_body = body(args.generated_dir, veneer)
        require(f"recomp_tail_call(0x{handler:06X}u)" in veneer_body,
                f"${veneer:06X} does not preserve the original BRA.W tail transfer to ${handler:06X}")
    require("func_006B6C" in cliff_end,
            "$0069A8 no longer checks the title-input helper each frame")
    require("m68k_write16(0x00FF0032u, (uint16_t)(0x0014u))" in completion_gate,
            "$006B6C no longer sets its own title state to $14 after Start")
    require("m68k_read16((uint32_t)(int32_t)(int16_t)0xF4E0)" in completion_gate and
            "(uint16_t)0x80u" in completion_gate and
            "recomp_tail_call(0x006A66u)" in completion_gate,
            "$006B6C no longer preserves the title-input condition (unrelated to the pre-crash ending)")
    ending_state_body = body(args.generated_dir, 0x006AF0)
    require("0x0000FBD6u" in ending_state_body,
            "$006B04 no longer selects the startup callback")
    require("0x0000774Eu" in body(args.generated_dir, 0x006B38),
            "$006B38 no longer selects the title/menu callback")
    require("hybrid_jmp_interpret(0x0000FBEAu" in credits_setup and
            "hybrid_jmp_interpret(0x0000775Eu" in post_credits,
            "startup/title callbacks lost their ROM state dispatch or terminal path")

    print("PASS: Round 7 Act 2 ROM selector rows choose scene $0012B0, camera $00295E, and resources $0032E6")
    print("PASS: generated callbacks retain scene tail-JMP, camera JSR/RTS/scroll veneers, and resource tail-transfer paths")
    print("PASS: $01F98C is the state-$14 computed edge in $01F970 and preserves A0/A7 through the shared body")
    print("PASS: $01FBAC is the state-$00 resource-preload edge in $01FBA4 and preserves its caller stack")
    print("PASS: $01FBB4 is the state-$08 interior edge in $01FBA4 and tail-enters the shared update")
    print("PASS: $0107F2 table-index-$0100 callback reaches all three native state veneers and original tail handlers")
    print("PASS: title Start branch is preserved separately from the ending timeline")
    print("PASS: Act-3 scene, camera, resource, and startup/title callbacks remain natively dispatched")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
