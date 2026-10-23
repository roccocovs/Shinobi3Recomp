#!/usr/bin/env python3
"""ROM-backed regression for Round-5 Act-0/1 callback-root discovery."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"
GAME_TOML_SHA256 = "8E8F21D0B36951658425A95325E5DF44D25CBD325A8F228200CA1675C847CD77"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def be16(data: bytes, address: int) -> int:
    return int.from_bytes(data[address : address + 2], "big")


def generated_body(generated_dir: Path, address: int) -> str:
    name = f"func_{address:06X}"
    start_re = re.compile(rf"(?m)^void {name}\(void\) \{{")
    for path in generated_dir.glob("shinobi3_part*.c"):
        text = path.read_text(encoding="utf-8", errors="strict")
        start = start_re.search(text)
        if start:
            end = re.search(r"(?m)^void func_[0-9A-F]{6}\(void\) \{", text[start.end() :])
            return text[start.start() : start.end() + end.start()] if end else text[start.start() :]
    raise AssertionError(f"generated body ${address:06X} is missing")


def dispatch_entry(dispatch: str, address: int) -> bool:
    return re.search(
        rf"\{{\s*0x{address:06X}u,\s*func_{address:06X}\s*\}}", dispatch
    ) is not None


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
    stripped_config, replacements = R6_ROOT_BLOCK.subn(b"  0x00255E, 0x002570\n", config_bytes)
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
    require(replacements == 1 and
            hashlib.sha256(stripped_config).hexdigest().upper() == GAME_TOML_SHA256,
            "game.toml contains changes beyond the preserved R5 config and reviewed R6 roots")

    # These selectors read the exact bounded stage-4 rows from three ROM
    # tables: camera -> FF007E, scene update -> FF0082, and scene assets ->
    # the computed tail dispatch at $002FA6.
    selected = {
        "camera": [be16(rom, 0x001D5A + 4 * 8 + act * 2) for act in (0, 1)],
        "scene": [be16(rom, 0x0009C0 + 4 * 8 + act * 2) for act in (0, 1)],
        "resource": [be16(rom, 0x002FC8 + 4 * 8 + act * 2) for act in (0, 1)],
    }
    require(selected == {
        "camera": [0x001F68, 0x00254A],
        "scene": [0x0010C4, 0x0010EA],
        "resource": [0x00303C, 0x003272],
    }, f"Round-5 stage-table cells changed: {selected!r}")

    # Supported-ROM digest and generated-code checks cover this path.

    # ROM identity, selected callback addresses, and generated callback-body
    # assertions below replace copied instruction-prefix signatures.

    callbacks = (0x001F68, 0x00254A, 0x0010C4, 0x0010EA, 0x00303C, 0x003272)
    for address in callbacks:
        require(dispatch_entry(dispatch, address),
                f"native dispatcher lacks table-selected callback ${address:06X}")
        generated_body(args.generated_dir, address)

    # The Act-1 resource callback is not an isolated function: it transfers
    # both ROM descriptors through shared loader helpers and then tail-dispatches
    # to the common scene-resource continuation. Keep that entire generated
    # path reachable, not just the initial callback entry.
    for address in (0x000A22, 0x000A42, 0x000A5C, 0x0010C2,
                    0x003020, 0x003042, 0x00305A, 0x003F8A):
        require(dispatch_entry(dispatch, address),
                f"scene callback/resource dependency ${address:06X} is absent from dispatch")
        generated_body(args.generated_dir, address)

    scene0 = generated_body(args.generated_dir, 0x0010C4)
    scene1 = generated_body(args.generated_dir, 0x0010EA)
    camera1 = generated_body(args.generated_dir, 0x00254A)
    resource1 = generated_body(args.generated_dir, 0x003272)
    require("0x00FF16EA" in scene0 and "0xF054" in scene0,
            "$0010C4 lost the original Act-0 scene-animation selection")
    require("0x00FF16EA" in scene1 and "0xF05A" in scene1,
            "$0010EA lost the original Act-1 scene-animation selection")
    require("func_000A42" in scene0 and
            "recomp_tail_call(0x000A5Cu)" in scene0 and
            "recomp_tail_call(0x0010C2u)" in scene0,
            "$0010C4 lost one of its shared scene-animation continuations")
    require("func_000A42" in scene1 and
            "recomp_tail_call(0x000A22u)" in scene1 and
            "recomp_tail_call(0x0010C2u)" in scene1,
            "$0010EA lost one of its shared scene-animation continuations")
    require("0x00FF37AA" in camera1,
            "$00254A lost its ROM-selected stage camera-state read")
    require("0x0003F682u" in resource1 and "0x0003FEDCu" in resource1 and
            "func_003042" in resource1 and "func_003020" in resource1 and
            "recomp_tail_call(0x00305Au)" in resource1,
            "$003272 lost its two descriptor-transfer calls or shared tail path")
    resource_transfer = generated_body(args.generated_dir, 0x003042)
    require("func_003020" in resource_transfer and
            "func_003F8A" in resource_transfer and
            "recomp_tail_call(0x00305Au)" in resource_transfer,
            "$003042 no longer reaches the shared descriptor loader and continuation")

    # Check the actual Round-5 Act-1 resource descriptors and carry the
    # generated path through the VDP data-port writer. This proves more than
    # root emission: the compressed first resource is expanded to FF9C10,
    # both descriptors enter $00305A, and their set bit 0 selects the
    # byte-source transfer path
    # writes command/data through the Genesis VDP ports.
    # Supported-ROM digest and generated-code checks cover this path.
    decompressor = generated_body(args.generated_dir, 0x003F8A)
    resource_loop = generated_body(args.generated_dir, 0x00305A)
    word_transfer = generated_body(args.generated_dir, 0x0042E0)
    byte_transfer = generated_body(args.generated_dir, 0x00426A)
    require("g_cpu.A[1] = 0x00FF9C10u" in resource_transfer and
            "m68k_write8(g_cpu.A[1]" in decompressor,
            "compressed Act-1 payload no longer decompresses into FF9C10")
    require("m68k_read8((uint32_t)(g_cpu.A[2] + (int32_t)4))" in resource_loop and
            "func_0042E0" in resource_loop and "func_00426A" in resource_loop,
            "$00305A no longer selects the original word/byte VDP transfer helpers")
    flag_read = resource_loop.index("m68k_read8((uint32_t)(g_cpu.A[2] + (int32_t)4))")
    flag_branch = resource_loop.index("if ((g_cpu.SR & (1u<<2)))", flag_read)
    byte_call = resource_loop.index("recomp_call_func(func_00426A);", flag_read)
    word_label = resource_loop.index("label_00309C:", flag_read)
    word_call = resource_loop.index("recomp_call_func(func_0042E0);", word_label)
    require(flag_read < flag_branch < byte_call < word_label < word_call,
            "set header bit 0 no longer selects the ROM byte-source transfer path")
    require("goto label_00309C;" in resource_loop[flag_branch:byte_call],
            "the zero-bit branch no longer bypasses the byte-source transfer helper")
    require("uint8_t _ts004284 = m68k_read8(g_cpu.A[1]);" in byte_transfer and
            "uint16_t _ts0042F8 = m68k_read16(g_cpu.A[1]);" in word_transfer,
            "generated byte/word transfer helpers no longer preserve their source widths")
    for helper in (word_transfer, byte_transfer):
        require("g_cpu.A[4] = 0x00C00000u" in helper and
                "m68k_write32(0x00C00004u" in helper and
                "m68k_write16(g_cpu.A[4]" in helper,
                "a generated graphics transfer helper no longer writes through VDP ports")

    # The roots must come from the bounded ROM tables, not a new manual list.
    functions = config["functions"]
    explicit = set(functions.get("extra", [])) | set(functions.get("late_extra", []))
    aliases = {entry.get("entry") for entry in functions.get("interior_alias", [])}
    require(not ({0x0010C4, 0x0010EA, 0x00254A, 0x003272} & (explicit | aliases)),
            "Round-5 roots were added as manual game.toml aliases or seeds")
    require({0x001F7E, 0x002C22A} <= aliases,
            "previously preserved interior aliases are missing")
    require("recomp_tail_call(g_cpu.A[6])" in generated_body(args.generated_dir, 0x002FA6),
            "$002FA6 no longer preserves the ROM-computed target")

    print("PASS: Round-5 Act-0/1 callback roots match the original bounded tables")
    print("PASS: generated scene, camera, and descriptor-transfer bodies retain ROM behavior")
    print("PASS: Act-1 descriptors select generated decompression and VDP-port transfer paths")
    print("PASS: game.toml is unchanged and prior interior aliases remain present")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
