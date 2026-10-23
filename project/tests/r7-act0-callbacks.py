#!/usr/bin/env python3
"""ROM-backed Round 7 Act 0 callback and graphics-path regression."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
STAGE_INDEX = 6
ACT_INDEX = 0
SCENE_TABLE = 0x0009C0
CAMERA_TABLE = 0x001D5A
RESOURCE_TABLE = 0x002FC8
CALLBACKS = (0x00114C, 0x0027AA, 0x0032B2)
CAMERA_ZONE_VENEERS = {
    0x00279A: 0x0027F2,
    0x00279E: 0x00283E,
    0x0027A2: 0x0028C8,
    0x0027A6: 0x0028C8,
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def word(data: bytes, address: int) -> int:
    return int.from_bytes(data[address:address + 2], "big")


def row(data: bytes, base: int, stage: int) -> tuple[int, ...]:
    return tuple(word(data, base + stage * 8 + act * 2) for act in range(4))


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
    raise AssertionError(f"generated body ${address:06X} is missing")


def dispatch_entry(text: str, address: int) -> bool:
    return re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", text) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--game-config", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
            "test requires the preserved original US ROM")

    # The stage-loader ROM table identifies this as internal stage index 6;
    # its selected Act-0 entries are exactly the three observed transition PCs.
    require(row(rom, SCENE_TABLE, STAGE_INDEX) ==
            (0x00114C, 0x0011E0, 0x0012B0, 0x000A00),
            "Round 7 scene/update table row changed")
    require(row(rom, CAMERA_TABLE, STAGE_INDEX) ==
            (0x0027AA, 0x00291C, 0x00295E, 0x001E16),
            "Round 7 camera callback table row changed")
    require(row(rom, RESOURCE_TABLE, STAGE_INDEX) ==
            (0x0032B2, 0x00303C, 0x0032E6, 0x001AB2),
            "Round 7 graphics-resource table row changed")

    # Selection mechanisms and call/return forms: FF0082 is tail-dispatched,
    # FF007E is invoked through JSR(A6), and the resource table uses JMP(A6).
    # Decode each ROM camera-zone veneer as BRA.W and calculate its target.
    for address, target in CAMERA_ZONE_VENEERS.items():
        require(word(rom, address) == 0x6000 and
                address + 2 + int.from_bytes(rom[address + 2:address + 4],
                                             "big", signed=True) == target,
                f"camera-zone BRA.W at ${address:06X} no longer targets ${target:06X}")

    config = tomllib.loads(args.game_config.read_text(encoding="utf-8"))
    roots = set(config["functions"].get("extra", [])) | set(config["functions"].get("late_extra", []))
    require(set(CALLBACKS) <= roots,
            "one or more ROM-selected Round 7 Act 0 callbacks are not configured as native roots")

    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    for address in CALLBACKS:
        require(dispatch_entry(dispatch, address),
                f"native dispatch lacks ROM-selected callback ${address:06X}")
    for address, target in CAMERA_ZONE_VENEERS.items():
        require(dispatch_entry(dispatch, address),
                f"native dispatch lacks zone-switch BRA.W veneer ${address:06X}")
        require(dispatch_entry(dispatch, target),
                f"native dispatch lacks zone handler ${target:06X}")
        veneer = body(args.generated_dir, address)
        require(f"recomp_tail_call(0x{target:06X}u)" in veneer,
                f"zone-switch veneer ${address:06X} no longer tail-dispatches to ${target:06X}")

    scene = body(args.generated_dir, 0x00114C)
    camera = body(args.generated_dir, 0x0027AA)
    resource = body(args.generated_dir, 0x0032B2)
    require("0x00FF16EA" in scene and "0xF07C" in scene and
            "0xF07E" in scene and "0x00FF0020" in scene and "return;" in scene,
            "$00114C scene callback lost its ROM-owned update and RTS path")
    require("0x00FF37AA" in camera and "func_0033C8" in camera and
            "hybrid_jmp_interpret(0x0000279Au" in camera,
            "$0027AA camera callback lost its zone selection/helper path")
    # The JMP-table helper resolves each selected BRA.W entry through the same
    # generated dispatcher, so the stage path remains native with floor=0.
    source_root = args.game_config.resolve().parents[2]
    glue = source_root / "engine" / "runner" / "glue.c"
    glue_text = glue.read_text(encoding="utf-8")
    require("call_by_address(target_pc);" in glue_text,
            "hybrid JMP dispatch no longer resolves its computed entry through generated native dispatch")
    require("0x0004030Au" in resource and "0x00FF37AA" in resource and
            "func_003020" in resource and "func_003F8A" in resource and
            "recomp_tail_call(0x00305Au)" in resource,
            "$0032B2 no longer selects zone graphics, expands them, and tail-transfers to the shared loader")

    # Keep dependencies that the selected resource path needs, and verify that
    # each generated entry remains present in the same dispatcher.
    for address in (0x003020, 0x00305A, 0x003F8A):
        require(dispatch_entry(dispatch, address),
                f"Round 7 resource dependency ${address:06X} is absent from native dispatch")
    require("recomp_call_addr(g_cpu.A[6])" in body(args.generated_dir, 0x001D38),
            "camera caller no longer uses the ordinary dynamically selected JSR/RTS path")

    print("PASS: Original stage-index-6 Act-0 scene, camera, and resource tables select $00114C/$0027AA/$0032B2")
    print("PASS: Native dispatch includes all three callbacks, four camera BRA.W veneers, and resource-loader dependencies")
    print("PASS: Scene tail-dispatch, camera JSR/RTS and zone-switch tails, and resource tail-transfer semantics are preserved")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
