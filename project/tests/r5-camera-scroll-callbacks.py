#!/usr/bin/env python3
"""ROM-backed regression for Round 5 Act 1's selected camera callbacks."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


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

    # $00254A indexes four longword callback pointers at PC-relative table
    # $00253A using FF37AA, then stores the selected pointer in FF007E.
    rows = tuple(int.from_bytes(rom[0x253A + i * 4:0x253E + i * 4], "big") for i in range(4))
    require(rows == (0x00255E, 0x00255E, 0x00255E, 0x002570),
            f"camera callback table at $00253A changed: {rows!r}")
    # Supported-ROM digest and generated-code checks cover this path.

    roots = set(config["functions"].get("extra", [])) | set(config["functions"].get("late_extra", []))
    require({0x00255E, 0x002570} <= roots,
            "the two authentic FF007E camera callbacks are not compiled as roots")
    require(0x002582 not in roots,
            "$002582 should be reached through its real JSR edges, not a guessed root")
    for address in (0x00255E, 0x002570, 0x002582, 0x001DFE, 0x003D54):
        require(has_dispatch_entry(dispatch, address),
                f"generated dispatch lacks camera path instruction entry ${address:06X}")
    callback = generated_body(args.generated_dir, 0x00255E)
    alternate = generated_body(args.generated_dir, 0x002570)
    helper = generated_body(args.generated_dir, 0x002582)
    calculation = generated_body(args.generated_dir, 0x001DFE)
    transfer = generated_body(args.generated_dir, 0x003D54)
    selector = generated_body(args.generated_dir, 0x00254A)
    dynamic_caller = generated_body(args.generated_dir, 0x001D38)

    require("0x00FF37AA" in selector and "0x00FF007E" in selector,
            "$00254A no longer selects the callback using FF37AA and stores FF007E")
    require("0x00FF007E" in dynamic_caller and
            "recomp_push_return(0x001D4Au)" in dynamic_caller and
            "recomp_call_addr(g_cpu.A[6]);" in dynamic_caller and
            "normal JSR pop" in dynamic_caller,
            "$001D48 dynamic camera callback call/ordinary RTS return path changed")

    for body, return_site in ((callback, 0x002564), (alternate, 0x002576)):
        require(f"recomp_push_return(0x{return_site:06X}u)" in body and
                "recomp_call_func(func_002582);" in body,
                f"camera callback JSR to $002582 lost its ordinary return path at ${return_site:06X}")
        require("0xF482" in body,
                "camera callback no longer stores its calculated Plane-B vertical scroll")
    require("recomp_push_return(0x002588u)" in helper and
            "recomp_call_func(func_001DFE);" in helper and "0xF082" in helper,
            "$002582 no longer calls the original $001DFE calculation and auxiliary scroll write")
    require("0xF480" in calculation and "0x00FF16C4" in calculation,
            "$001DFE no longer writes the ROM-derived Plane-A scroll from live camera state")
    require("0x40000090u" in transfer and "0xF480" in transfer and
            "g_cpu.A[6] + (int32_t)-4" in transfer,
            "$003D54/$003DB4 no longer transfers both RAM scroll words through the VDP port")
    require("0x100u" in callback and "0x70u" in alternate,
            "the two ROM callback offsets were not preserved in generated code")

    print("PASS: $00254A's ROM table selects compiled $00255E/$002570 callback entries")
    print("PASS: generated JSR/RTS path reaches $002582 -> $001DFE and writes live scroll buffers")
    print("PASS: original $003DB4 VDP writer transfers $FFF480/$FFF482 values to VDP")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
