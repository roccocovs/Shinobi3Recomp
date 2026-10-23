#!/usr/bin/env python3
"""ROM-backed Round-7 Act-1 foreground/scene callback coverage regression."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
R7_ACT0_CONFIG_SHA256 = "99DE6153B032B1C6026FD240BD742D3E870BE39017DA8889D14FB5928CFBC967"
STAGE_INDEX = 6
SCENE_TABLE = 0x0009C0
CAMERA_TABLE = 0x001D5A
RESOURCE_TABLE = 0x002FC8
SCENE_CALLBACK = 0x0011E0
CAMERA_CALLBACK = 0x00291C
RESOURCE_CALLBACK = 0x00303C
ACT1_CONFIG_BLOCK = (
    b"  # Round 7 Act 1 selects scene callback $0011E0 through FF0082 and camera\n"
    b"  # callback $00291C through FF007E. $00303C is its shared resource callback.\n"
    b"  0x0011E0, 0x00291C,\n"
)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def word(data: bytes, address: int) -> int:
    return int.from_bytes(data[address:address + 2], "big")


def row(data: bytes, base: int) -> tuple[int, ...]:
    return tuple(word(data, base + STAGE_INDEX * 8 + act * 2) for act in range(4))


def generated_body(directory: Path, address: int) -> str:
    name = f"func_{address:06X}"
    start_re = re.compile(rf"(?m)^void {name}\(void\) \{{")
    for path in directory.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8")
        start = start_re.search(text)
        if start:
            after = text[start.end():]
            end = re.search(r"(?m)^void func_[0-9A-F]{6}\(void\) \{", after)
            return text[start.start():start.end() + end.start()] if end else text[start.start():]
    raise AssertionError(f"generated native body ${address:06X} is missing")


def dispatch_entry(dispatch: str, address: int) -> bool:
    return re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--game-config", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    config_bytes = args.game_config.read_bytes()
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
            "test requires the preserved original US ROM")
    require(row(rom, SCENE_TABLE) == (0x00114C, 0x0011E0, 0x0012B0, 0x000A00),
            "Round 7 scene table row changed")
    require(row(rom, CAMERA_TABLE) == (0x0027AA, 0x00291C, 0x00295E, 0x001E16),
            "Round 7 camera table row changed")
    require(row(rom, RESOURCE_TABLE) == (0x0032B2, 0x00303C, 0x0032E6, 0x001AB2),
            "Round 7 resource table row changed")
    # Supported-ROM digest and generated-code checks cover this path.

    config = tomllib.loads(config_bytes.decode("utf-8"))
    roots = set(config["functions"].get("extra", [])) | set(config["functions"].get("late_extra", []))
    require({SCENE_CALLBACK, CAMERA_CALLBACK, RESOURCE_CALLBACK} <= roots,
            "one or more Round 7 Act 1 callbacks is absent from native roots")
    stripped_config = config_bytes.replace(ACT1_CONFIG_BLOCK, b"", 1)
    stripped_config = stripped_config.replace(b'  # The ending timeline installs this HBlank RTE handler into FF0006 at\n  # $0105EE. Its native entry is required for the later raster phase.\n  ,0x010A02\n', b"", 1)
    stripped_config = stripped_config.replace(
        b"  # Round 7 Act 2 selects final-boss scene, camera, and resource callbacks.\n"
        b"  0x0012B0, 0x00295E, 0x0032E6,\n", b"", 1)
    ending_handler_roots = (
        b"  # Object table index $0100 selects this animation handler from the pointer table\n"
        b"  # at $0365A2. The scheduler calls it through JSR (A6), and the handler's\n"
        b"  # PC-indexed state ladder selects its native animation/setup branches.\n"
        b"  0x0107F2,\n"
        b"  # $0107F8 jumps into three BRA.W veneers immediately before the handler\n"
        b"  # root. The object state selects these by +0/+4/+8; keep the selected\n"
        b"  # continuations as native tail-dispatch targets so each state body runs\n"
        b"  # with the scheduler's live A0 and original stack.\n"
        b"  0x0107E6, 0x0107EA, 0x0107EE,\n"
        b"  # The veneer destinations are distinct RTS-terminated object-state bodies.\n"
        b"  # They are selected by the live callback's PC-indexed JMP and return through\n"
        b"  # the scheduler's existing JSR(A6) frame.\n"
        b"  0x01083C, 0x010948, 0x010976\n"
    )
    stripped_config = stripped_config.replace(ending_handler_roots, b"", 1)
    stripped_config = stripped_config.replace(
        b"  0x0027AA, 0x00326C, 0x003292, 0x0032B2,\n]\n",
        b"  0x0027AA, 0x00326C, 0x003292, 0x0032B2\n]\n", 1)
    final_boss_alias = (
        b"\n# Object state 0x14 selects $01F98C from the PC-indexed JMP at $01F974.\n"
        b"# Keep it in the $01F970 execution body so A0 and the existing caller stack\n"
        b"# remain intact while the state advances and dispatches to $01FB06.\n"
        b"[[functions.interior_alias]]\nentry = 0x01F98C\nowner = 0x01F970\n"
        b"jump = 0x01F974\n"
    )
    stripped_config = stripped_config.replace(final_boss_alias, b"", 1)
    preload_alias = (
        b"\n# The next stage-resource preloader is an object state selected by the\n"
        b"# computed JMP at $01FBA8. Keep its stage increment, shared loader call, and\n"
        b"# ordinary RTS in the existing $01FBA4 body with A0/A7 intact.\n"
        b"[[functions.interior_alias]]\nentry = 0x01FBAC\nowner = 0x01FBA4\n"
        b"jump = 0x01FBA8\n"
    )
    stripped_config = stripped_config.replace(preload_alias, b"", 1)
    state_update_alias = (
        b"\n# Object state +$08 selects $01FBB4 from the same computed JMP. Keep this\n"
        b"# BRA.W in the $01FBA4 body so it retains the live object register and caller\n"
        b"# stack before tail-entering the shared actor update at $01FBE6.\n"
        b"[[functions.interior_alias]]\nentry = 0x01FBB4\nowner = 0x01FBA4\n"
        b"jump = 0x01FBA8\n"
    )
    stripped_config = stripped_config.replace(state_update_alias, b"", 1)
    require(config_bytes.count(ACT1_CONFIG_BLOCK) == 1 and
            hashlib.sha256(stripped_config).hexdigest().upper() == R7_ACT0_CONFIG_SHA256,
            "Round 7 Act 1 root block differs from the reviewed isolated additions")

    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    for address in (SCENE_CALLBACK, CAMERA_CALLBACK, RESOURCE_CALLBACK):
        require(dispatch_entry(dispatch, address),
                f"native dispatch lacks selected Act-1 callback ${address:06X}")
        generated_body(args.generated_dir, address)

    scene = generated_body(args.generated_dir, SCENE_CALLBACK)
    camera = generated_body(args.generated_dir, CAMERA_CALLBACK)
    resource = generated_body(args.generated_dir, RESOURCE_CALLBACK)
    caller = generated_body(args.generated_dir, 0x001D38)
    require("0x00FF16EA" in scene and "0xF058" in scene and "0xF076" in scene and
            "func_000A02" in scene and "recomp_tail_call(0x00117Eu)" in scene and
            "recomp_tail_call(0x000A5Cu)" in scene,
            "$0011E0 lost its ROM-selected scene-animation work or tail continuations")
    require("0x00FF37AA" in camera and "0x10EEu" in camera and
            "0xE000" in camera and "0xE010" in camera and "func_00342E" in camera and
            "func_001DFE" in camera and "0xF082" in camera and "0xF482" in camera,
            "$00291C lost its zone-selected scroll calculation or scroll-buffer writes")
    stack_returns = (0x0016C6, 0x001706, 0x001728, 0x004DC4, 0x01FD68,
                     0x021428, 0x021462, 0x021A62, 0x0266A2, 0x02696C,
                     0x0291D4, 0x029D5E, 0x02BD3C, 0x02BD12, 0x02BC3A)
    for address in stack_returns:
        require(f"0x{address:06X}u" in camera,
                f"$00291C lost a ROM-supported stack return path to ${address:06X}")
    require("func_003000" in resource and "recomp_tail_call(0x003042u)" in resource,
            "$00303C no longer enters the original shared resource loader")
    require("recomp_call_addr(g_cpu.A[6]);" in caller and "normal JSR pop" in caller,
            "$001D38 no longer preserves ordinary callback JSR/RTS behavior")

    print("PASS: Round 7 Act 1 ROM selector rows choose scene $0011E0, camera $00291C, and resource $00303C")
    print("PASS: scene animation and zone-selected camera scroll work remain in generated native bodies")
    print("PASS: resource-loader path, camera JSR/RTS, and all 15 camera stack-return paths are preserved")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
