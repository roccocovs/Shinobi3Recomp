#!/usr/bin/env python3
"""ROM-backed checks for the Round 4 Act 1 callback dispatch correction."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def be16(data: bytes, address: int) -> int:
    return int.from_bytes(data[address : address + 2], "big")


def be32(data: bytes, address: int) -> int:
    return int.from_bytes(data[address : address + 4], "big")


def generated_body(generated_dir: Path, address: int) -> str:
    name = f"func_{address:06X}"
    start_re = re.compile(rf"(?m)^void {name}\(void\) \{{")
    for path in generated_dir.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        start = start_re.search(text)
        if start:
            end = re.search(r"(?m)^void func_[0-9A-F]{6}\(void\) \{", text[start.end() :])
            return text[start.start() : start.end() + end.start()] if end else text[start.start() :]
    raise AssertionError(f"generated native body ${address:06X} is missing")


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
            "the tested ROM is not the preserved US ROM used by Pass87")

    # These three independent original tables select callbacks for internal
    # stage 3 / Act 1 using the recorded, zero-based stage and act selectors.
    selections = {
        "camera": be16(rom, 0x001D5A + 3 * 8 + 1 * 2),
        "scene": be16(rom, 0x0009C0 + 3 * 8 + 1 * 2),
        "stage_event": be32(rom, 0x039602 + 3 * 8 + 1 * 4),
    }
    require(selections == {"camera": 0x0024AE, "scene": 0x0010A2,
                           "stage_event": 0x0003929E},
            f"Round 4 Act 1 ROM callback cells changed: {selections!r}")

    extra = set(config["functions"]["extra"])
    for address in (0x0024AE, 0x0010A2, 0x03929E):
        require(address in extra, f"game.toml does not seed verified callback ${address:06X}")
        require(re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch),
                f"native dispatcher lacks selected callback ${address:06X}")

    # Exact callback starts and the original selector/call flow.
    # Supported-ROM digest and generated-code checks cover this path.

    # $03929E's PC-indexed table is exactly two BRA.W rows: initial state 0
    # reaches $0392B0; state 4 reaches $03935A. Both are verified instruction
    # destinations and are generated alongside the callback body.
    # Supported-ROM digest and generated-code checks cover this path.
    require(0x0392AA + be16(rom, 0x0392AA) == 0x0392B0 and
            0x0392AE + be16(rom, 0x0392AE) == 0x03935A,
            "$03929E BRA.W entries no longer lead to their verified handlers")
    for address in (0x0392A8, 0x0392AC, 0x0392B0, 0x03935A):
        require(re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch),
                f"native dispatch lacks $03929E state destination ${address:06X}")

    # Generated bodies must retain the actual original effects. The first
    # callback writes scroll state and fills the F080 buffer through helpers;
    # the second writes the frame-selected F05E value and requests VDP update;
    # the third preserves the state selector and its ROM-computed branch.
    camera = generated_body(args.generated_dir, 0x0024AE)
    require(all(token in camera for token in (
        "0xE004", "0xF480", "0xF482", "0x00FF01B8",
        "func_001DC4", "func_0036B0", "func_0036C2", "func_0036C8",
        "func_001D92", "func_00367A")),
        "$0024AE generated body lost original camera/scroll buffer operations")

    scene = generated_body(args.generated_dir, 0x0010A2)
    require(all(token in scene for token in (
        "0x00FF16EA", "0x00D0u", "(-48)", "0xF05E",
        "m68k_write16(g_cpu.A[1]", "m68k_write8(0x00FF0020u")),
            "$0010A2 generated body lost its frame lookup, F05E write, or update request")

    event = generated_body(args.generated_dir, 0x03929E)
    require("0x00FF5F00" in event and "hybrid_jmp_interpret(0x000392A8u" in event,
            "$03929E generated body lost the original computed state dispatch")
    initial = generated_body(args.generated_dir, 0x0392B0)
    require(all(token in initial for token in ("0x00FF5F02", "0x00FF5F03",
                                                "0x00080000", "func_003F8A",
                                                "m68k_write16(0x00FF5F00u",
                                                "(uint16_t)4u")),
            "$03929E state-zero resource setup was not generated")
    active = generated_body(args.generated_dir, 0x03935A)
    require("0x00FF5F02" in active and "0x00FF5F03" in active,
            "$03929E state-four handler lost its original event counters")

    print("PASS: original stage-3/Act-1 tables select $0024AE, $0010A2, and $03929E")
    print("PASS: native dispatch includes all selected callbacks and both $03929E BRA.W paths")
    print("PASS: generated callbacks retain camera scroll, scene update, and state-zero resource loading")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
