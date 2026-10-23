#!/usr/bin/env python3
"""ROM-backed regression for Round 6 Act 1's scene and camera callbacks."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
STAGE_INDEX = 5
ACT_INDEX = 1
SCENE_CALLBACK_TABLE = 0x0009C0
CAMERA_CALLBACK_TABLE = 0x001D5A
RESOURCE_CALLBACK_TABLE = 0x002FC8


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def table_row(rom: bytes, base: int, stage: int) -> tuple[int, int, int, int]:
    return tuple(
        int.from_bytes(rom[base + stage * 8 + act * 2:base + stage * 8 + act * 2 + 2], "big")
        for act in range(4)
    )


def generated_body(directory: Path, address: int) -> str:
    name = f"func_{address:06X}"
    start_re = re.compile(rf"(?m)^void {name}\(void\) \{{")
    for path in directory.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        start = start_re.search(text)
        if start:
            end = re.search(r"(?m)^void func_[0-9A-F]{6}\(void\) \{", text[start.end():])
            return text[start.start():start.end() + end.start()] if end else text[start.start():]
    raise AssertionError(f"generated body ${address:06X} is missing")


def instruction_owner_body(directory: Path, address: int) -> str:
    needle = f"/* ${address:06X} */"
    for path in directory.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        marker = text.find(needle)
        if marker < 0:
            continue
        start = text.rfind("void func_", 0, marker)
        end = re.search(r"(?m)^void func_[0-9A-F]{6}\(void\) \{", text[marker:])
        if start < 0:
            continue
        return text[start:marker + end.start()] if end else text[start:]
    raise AssertionError(f"generated instruction ${address:06X} is missing")


def has_dispatch_entry(text: str, address: int) -> bool:
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
    config = tomllib.loads(args.game_config.read_text(encoding="utf-8"))
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    roots = set(config["functions"].get("extra", [])) | set(config["functions"].get("late_extra", []))

    camera_row = table_row(rom, CAMERA_CALLBACK_TABLE, STAGE_INDEX)
    scene_row = table_row(rom, SCENE_CALLBACK_TABLE, STAGE_INDEX)
    resource_row = table_row(rom, RESOURCE_CALLBACK_TABLE, STAGE_INDEX)
    require(camera_row == (0x00261C, 0x002710, 0x002776, 0x001E16),
            f"Round 6 camera callback row changed: {camera_row!r}")
    require(scene_row == (0x000A00, 0x001120, 0x000A00, 0x000A00),
            f"Round 6 scene-frame callback row changed: {scene_row!r}")
    require(resource_row == (0x003292, 0x00303C, 0x00326C, 0x001AB2),
            f"Round 6 scene-resource callback row changed: {resource_row!r}")

    # Supported-ROM digest and generated-code checks cover this path.

    # Supported-ROM digest and generated-code checks cover this path.

    require({0x001120, 0x002710} <= roots,
            "the ROM-selected Round 6 Act 1 scene/camera callbacks are not native roots")
    require(has_dispatch_entry(dispatch, 0x001120) and has_dispatch_entry(dispatch, 0x002710),
            "generated dispatch does not expose both Round 6 Act 1 callback entries")
    for address in (0x000A00, 0x001D0A, 0x001D38, 0x00261C, 0x00303C, 0x003516, 0x003598):
        require(has_dispatch_entry(dispatch, address),
                f"generated dispatch lost callback dependency ${address:06X}")

    scene = generated_body(args.generated_dir, 0x001120)
    camera = generated_body(args.generated_dir, 0x002710)
    scene_tail_dispatch = instruction_owner_body(args.generated_dir, 0x0009BE)
    camera_caller = generated_body(args.generated_dir, 0x001D38)
    require("0x00FF16EA" in scene and "0xF058" in scene and
            scene.count("m68k_write16(g_cpu.A[2]") == 2 and "g_cpu.A[2] += 2;" in scene and
            "0x00FF0020" in scene and "return;" in scene,
            "$001120 generated body lost phase-driven scene-buffer writes or its ordinary RTS")
    require("0x00FF37AA" in camera and "0x00FF16C4" in camera and "0xF480" in camera and
            "0xF482" in camera and "recomp_call_func(func_003598);" in camera and
            "recomp_tail_call(0x003516u);" in camera,
            "$002710 generated body lost its ROM camera calculations or shared continuation")
    require("0x00FF0082" in scene_tail_dispatch and "recomp_tail_call(g_cpu.A[6]);" in scene_tail_dispatch,
            "$0009BE no longer tail-dispatches the FF0082 scene callback")
    require("recomp_push_return(0x001D4Au)" in camera_caller and
            "recomp_call_addr(g_cpu.A[6]);" in camera_caller and "normal JSR pop" in camera_caller,
            "$001D38 no longer preserves the camera callback's ordinary JSR/RTS return")

    print("PASS: Original Round 6 Act 1 tables select scene callback $001120, camera callback $002710, and resource callback $00303C")
    print("PASS: Native dispatch includes both callbacks and keeps their original RTS/tail-JMP continuations")
    print("PASS: Scene phase writes and ROM-derived camera/scroll transfers survive code generation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
