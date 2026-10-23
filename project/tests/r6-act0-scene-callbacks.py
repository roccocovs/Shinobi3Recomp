#!/usr/bin/env python3
"""ROM-backed coverage for Round 6 Act 0 scene and camera callbacks."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
R5_GAME_TOML_SHA256 = "8E8F21D0B36951658425A95325E5DF44D25CBD325A8F228200CA1675C847CD77"
accepted_later_roots = "\n".join(
    [
        '  0x00255E, 0x002570,',
        '  # Round 6 paths selected by the original stage/act callback tables.',
        '  # $001E16 is the empty Act-3 RTS callback; $00326C is the Act-2 VDP',
        '  # fill callback; Round 6 Act 0 selects scene loader $003292 and camera',
        '  # updater $00261C. Keep their existing RTS/tail-JMP semantics.',
        '  # Round 6 Act 1 selects scene-frame callback $001120 through $FF0082 and',
        '  # camera updater $002710 through $FF007E. The former returns through the',
        '  # original tail-JMP callback path; the latter tail-jumps into $003516 after',
        '  # updating the stage scroll work values.',
        '  # Round 6 Act 2 selects camera callback $002776 through $FF007E. It is a',
        '  # separate RTS routine that initializes the boss-room scroll work values.',
        '  # Round 7 (stage index 6), Act 0 selects scene callback $00114C through',
        '  # FF0082, camera callback $0027AA through FF007E, and resource callback',
        '  # $0032B2 through the stage/act JMP selector at $002FA6. Preserve the scene',
        "  # callback's tail-dispatch return, the camera callback's ordinary JSR/RTS,",
        "  # and the resource callback's tail-transfer into the shared loader.",
        '  0x001E16, 0x001120, 0x00114C, 0x00261C, 0x002710, 0x002776,',
        "  # $0027AA's zone switch is a PC-indexed table of four BRA.W veneers at",
        '  # $00279A/$00279E/$0027A2/$0027A6. Keep those actual indirect JMP targets',
        '  # in native dispatch; each tail-branches to the corresponding zone handler.',
        '  0x00279A, 0x00279E, 0x0027A2, 0x0027A6,',
        '  0x0027AA, 0x00326C, 0x003292, 0x0032B2,',
        '  # Round 7 Act 1 selects scene callback $0011E0 through FF0082 and camera',
        '  # callback $00291C through FF007E. $00303C is its shared resource callback.',
        '  0x0011E0, 0x00291C,',
        '  # Round 7 Act 2 selects final-boss scene, camera, and resource callbacks.',
        '  0x0012B0, 0x00295E, 0x0032E6,',
        '  # Object table index $0100 selects this animation handler from the pointer table',
        '  # at $0365A2. The scheduler calls it through JSR (A6), and the handler\'s',
        '  # PC-indexed state ladder selects its native animation/setup branches.',
        '  0x0107F2,',
        '  # $0107F8 jumps into three BRA.W veneers immediately before the handler',
        '  # root. The object state selects these by +0/+4/+8; keep the selected',
        '  # continuations as native tail-dispatch targets so each state body runs',
        '  # with the scheduler\'s live A0 and original stack.',
        '  0x0107E6, 0x0107EA, 0x0107EE,',
        '  # The veneer destinations are distinct RTS-terminated object-state bodies.',
        '  # They are selected by the live callback\'s PC-indexed JMP and return through',
        '  # the scheduler\'s existing JSR(A6) frame.',
        '  0x01083C, 0x010948, 0x010976',
    ]
) + "\n"
R6_ROOT_BLOCK = re.compile(re.escape(accepted_later_roots.encode("utf-8")))


def require(condition: bool, message: str) -> None:
    if not condition:
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


def dispatch_entry(dispatch: str, address: int) -> bool:
    return re.search(rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch) is not None


def table_row(rom: bytes, base: int, stage: int) -> tuple[int, int, int, int]:
    return tuple(int.from_bytes(rom[base + stage * 8 + act * 2:base + stage * 8 + act * 2 + 2], "big")
                 for act in range(4))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--game-config", required=True, type=Path)
    parser.add_argument("--generated-dir", required=True, type=Path)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    config_bytes = args.game_config.read_bytes()
    config = tomllib.loads(config_bytes.decode("utf-8"))
    dispatch = (args.generated_dir / "shinobi3_dispatch.c").read_text(encoding="utf-8")
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256,
            "the ROM differs from the preserved US image")
    stripped_config, count = R6_ROOT_BLOCK.subn(b"  0x00255E, 0x002570\n", config_bytes)
    final_boss_alias = (
        b"\n# Object state 0x14 selects $01F98C from the PC-indexed JMP at $01F974.\n"
        b"# Keep it in the $01F970 execution body so A0 and the existing caller stack\n"
        b"# remain intact while the state advances and dispatches to $01FB06.\n"
        b"[[functions.interior_alias]]\nentry = 0x01F98C\nowner = 0x01F970\n"
        b"jump = 0x01F974\n"
    )
    stripped_config = stripped_config.replace(
        b"  # Round 7 Act 2 selects final-boss scene, camera, and resource callbacks.\n"
        b"  0x0012B0, 0x00295E, 0x0032E6,\n"
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
        b"  0x01083C, 0x010948, 0x010976\n", b"", 1)
    stripped_config = stripped_config.replace(b'  # The ending timeline installs this HBlank RTE handler into FF0006 at\n  # $0105EE. Its native entry is required for the later raster phase.\n  ,0x010A02\n', b"", 1)
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
    require(count == 1 and hashlib.sha256(stripped_config).hexdigest().upper() == R5_GAME_TOML_SHA256,
            "only the reviewed R6 callback roots may be added to the accepted R5 config")

    roots = set(config["functions"].get("extra", [])) | set(config["functions"].get("late_extra", []))
    required_roots = {0x001E16, 0x00261C, 0x00326C, 0x003292}
    require(required_roots <= roots, "one or more ROM-selected callback roots are missing")

    # Stage index 4 / Act 1 is the established Round 5 Act 1 selector; index 5
    # is the following Round 6 Act 0 row in these same original ROM tables.
    camera5 = table_row(rom, 0x001D5A, 5)
    scene5 = table_row(rom, 0x0009C0, 5)
    resource5 = table_row(rom, 0x002FC8, 5)
    require(table_row(rom, 0x001D5A, 4)[1] == 0x00254A and
            table_row(rom, 0x002FC8, 4)[1] == 0x003272,
            "Round 5 Act 1 table row changed; stage-index mapping must be revalidated")
    require(camera5 == (0x00261C, 0x002710, 0x002776, 0x001E16),
            f"Round 6 camera callback row changed: {camera5!r}")
    require(scene5 == (0x000A00, 0x001120, 0x000A00, 0x000A00),
            f"Round 6 scene-frame callback row changed: {scene5!r}")
    require(resource5 == (0x003292, 0x00303C, 0x00326C, 0x001AB2),
            f"Round 6 scene-resource callback row changed: {resource5!r}")

    # Supported-ROM digest and generated-code checks cover this path.

    addresses = (0x001E16, 0x00261C, 0x00326C, 0x003292)
    for address in addresses:
        require(dispatch_entry(dispatch, address),
                f"generated dispatcher lacks table-selected callback ${address:06X}")
        generated_body(args.generated_dir, address)

    selector = generated_body(args.generated_dir, 0x001D0A)
    camera_caller = generated_body(args.generated_dir, 0x001D38)
    scene_selector = generated_body(args.generated_dir, 0x002FA6)
    camera = generated_body(args.generated_dir, 0x00261C)
    scene_loader = generated_body(args.generated_dir, 0x003292)
    act2_fill = generated_body(args.generated_dir, 0x00326C)
    empty_callback = generated_body(args.generated_dir, 0x001E16)

    require("0x00FF37A6" in selector and "0x00FF37A8" in selector and "0x00FF007E" in selector,
            "$001D0A no longer selects the per-frame camera callback from ROM state")
    require("recomp_push_return(0x001D4Au)" in camera_caller and
            "recomp_call_addr(g_cpu.A[6]);" in camera_caller and "normal JSR pop" in camera_caller,
            "$001D38 no longer preserves the callback's ordinary JSR/RTS return and SR restoration")
    require("recomp_tail_call(g_cpu.A[6]);" in scene_selector,
            "$002FA6 no longer preserves its original JMP(A6) tail-dispatch semantics")
    require("0x00FF37AA" in camera and "0x00FF01BC" in camera and "0xF480" in camera and
            "0x00342E" in camera,
            "$00261C lost its original stage-selected scroll generation/transfer path")
    require("0x0003FF2Au" in scene_loader and "0x00040188u" in scene_loader and
            "func_003020" in scene_loader and "func_00305A" in scene_loader and
            "recomp_tail_call(0x003042u)" in scene_loader,
            "$003292 lost either ROM descriptor transfer or its final shared loader tail call")
    require("recomp_tail_call(0x0045AAu)" in act2_fill,
            "$00326C no longer preserves its ROM-selected VDP-fill tail call")
    require("return;" in empty_callback,
            "$001E16's valid RTS/no-op callback no longer returns normally")

    for address in (0x000A00, 0x001D96, 0x003020, 0x003042, 0x00305A,
                    0x003F8A, 0x00426A, 0x0042E0, 0x0045AA, 0x00342E):
        require(dispatch_entry(dispatch, address),
                f"generated dependency ${address:06X} is missing from dispatch")

    print("PASS: ROM tables select $003292 scene resources and $00261C camera updater for Round 6 Act 0")
    print("PASS: generated resource loader preserves descriptors, transfer helpers, and JMP-tail semantics")
    print("PASS: generated camera callback preserves FF007E JSR/RTS return behavior and shared scroll path")
    print("PASS: $00326C Act-2 VDP callback and $001E16 no-op callback retain their original return semantics")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
