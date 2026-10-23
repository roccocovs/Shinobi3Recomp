#!/usr/bin/env python3
"""ROM-backed test for the Round 6 Act 2 camera callback used in the boss room."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
STAGE_INDEX = 5
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
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
            "test requires the preserved original US ROM")

    camera_row = table_row(rom, CAMERA_CALLBACK_TABLE, STAGE_INDEX)
    resource_row = table_row(rom, RESOURCE_CALLBACK_TABLE, STAGE_INDEX)
    require(camera_row == (0x00261C, 0x002710, 0x002776, 0x001E16),
            f"Round 6 camera table changed: {camera_row!r}")
    require(resource_row == (0x003292, 0x00303C, 0x00326C, 0x001AB2),
            f"Round 6 scene-resource table changed: {resource_row!r}")

    # $001D0A installs the camera table's stage/act-selected address into
    # $FF007E. $001D38 invokes that address with JSR(A6), preserves SR, and
    # resumes at $001D4A after the callback's ordinary RTS.
    # Supported-ROM digest and generated-code checks cover this path.

    # This table-selected target is a complete standalone callback: it begins
    # at $002776 and returns with RTS at $002798. It clears the horizontal
    # scroll work fields, sets the boss-room base offset, derives $FFF480 from
    # live $FF16C4, and initializes $FFF482. It does not upload graphics.
    # Supported-ROM digest and generated-code checks cover this path.
    roots = set(config["functions"].get("extra", [])) | set(config["functions"].get("late_extra", []))
    require(0x002776 in roots,
            "$002776 is selected by the Round 6 Act 2 camera table but is not a native root")
    require(dispatch_entry(dispatch, 0x002776),
            "generated dispatch cannot enter the table-selected $002776 callback")
    require(dispatch_entry(dispatch, 0x001D0A) and dispatch_entry(dispatch, 0x001D38),
            "generated dispatch lost the ROM camera selector or its JSR caller")

    callback = generated_body(args.generated_dir, 0x002776)
    caller = generated_body(args.generated_dir, 0x001D38)
    require("recomp_push_return(0x001D4Au)" in caller and
            "recomp_call_addr(g_cpu.A[6]);" in caller and "normal JSR pop" in caller,
            "generated camera caller no longer preserves the callback's ordinary JSR/RTS return")
    require("0xE000" in callback and "0xF080" in callback and
            "0xE004" in callback and "0x00FF16C4" in callback and
            "0xF480" in callback and "0xF482" in callback,
            "generated callback lost one or more ROM scroll-state writes")
    require("0xFFE8" in callback or "0xFFFFE8" in callback,
            "generated callback lost the ROM-defined $FFE8 base offset")
    require("0x0100" in callback or "0x100" in callback,
            "generated callback lost the ROM-defined $0100 Plane B offset")
    require("return;" in callback,
            "generated callback no longer performs the normal RTS return")

    # The act-2 resource callback is a separate, already-generated VDP fill;
    # the camera callback's missing dispatch must not be mistaken for an asset
    # upload routine.
    require(dispatch_entry(dispatch, 0x00326C) and dispatch_entry(dispatch, 0x0045AA),
            "the existing Act-2 VDP fill callback/dependency is missing")
    resource = generated_body(args.generated_dir, 0x00326C)
    require("recomp_tail_call(0x0045AAu);" in resource,
            "$00326C no longer preserves the original VDP-fill tail call")

    print("PASS: the Round 6 Act 2 table selects $002776 and its JSR/RTS ownership is valid")
    print("PASS: native $002776 emits the ROM camera/scroll writes and returns normally")
    print("PASS: the separate Act-2 $00326C->$0045AA VDP-fill path remains intact")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
