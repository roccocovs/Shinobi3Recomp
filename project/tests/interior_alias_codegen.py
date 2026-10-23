#!/usr/bin/env python3
"""Codegen regression tests for explicitly declared interior dispatch aliases."""

# Byte strings below construct synthetic instruction fixtures for the
# recompiler; they are not extracts from Shinobi III or another commercial ROM.

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys
import uuid

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def put32(buf: bytearray, address: int, value: int) -> None:
    buf[address : address + 4] = value.to_bytes(4, "big")


def rom_image(reset_pc: int, blocks: list[tuple[int, bytes]]) -> bytes:
    image_size = max([0x2200] + [address + len(code) for address, code in blocks])
    image = bytearray(image_size)
    put32(image, 0, 0x00FFFFF0)
    put32(image, 4, reset_pc)
    image[0x100:0x10F] = b"SEGA GENESIS ".ljust(0x0F, b" ")
    image[0x120:0x150] = b"INTERIOR ALIAS CODEGEN FIXTURE".ljust(0x30, b" ")
    image[0x150:0x180] = b"INTERIOR ALIAS CODEGEN FIXTURE".ljust(0x30, b" ")
    image[0x1F0:0x1F3] = b"USA"
    for address, code in blocks:
        image[address : address + len(code)] = code
    if image[0x100:0x10F] != b"SEGA GENESIS ".ljust(0x0F, b" "):
        raise AssertionError("synthetic code overwrote the Genesis ROM header")
    return bytes(image)


def alias_table(entry: int, owner: int, jump: int | None = None) -> str:
    jump_line = f"jump = 0x{jump:06X}\n" if jump is not None else ""
    return (
        "\n[[functions.interior_alias]]\n"
        f"entry = 0x{entry:06X}\n"
        f"owner = 0x{owner:06X}\n"
        f"{jump_line}"
    )


def write_case(root: pathlib.Path, name: str, rom: bytes,
               config: str) -> tuple[pathlib.Path, pathlib.Path]:
    case_dir = root / f"{name}-{uuid.uuid4().hex[:10]}"
    output_dir = case_dir / "generated"
    output_dir.mkdir(parents=True)
    (case_dir / "fixture.bin").write_bytes(rom)
    (case_dir / "game.toml").write_text(config, encoding="utf-8")
    return case_dir, output_dir


def run_generator(exe: pathlib.Path, case_dir: pathlib.Path,
                  output_dir: pathlib.Path) -> tuple[int, str]:
    result = subprocess.run(
        [str(exe), str(case_dir / "fixture.bin"), "--game",
         str(case_dir / "game.toml"), "--output-dir", str(output_dir),
         "--reverse-debug"],
        text=True, capture_output=True, timeout=90, check=False,
    )
    combined = result.stdout + result.stderr
    (case_dir / "recompiler.log").write_text(combined, encoding="utf-8")
    return result.returncode, combined


def generated_source(output_dir: pathlib.Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(output_dir.glob("*_part*.c"))
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_case(exe: pathlib.Path, root: pathlib.Path, name: str,
             rom: bytes, config: str) -> tuple[pathlib.Path, pathlib.Path, int, str]:
    # The generator requires the table itself; all layout keys default to 0.
    # Keep each case's game/functions settings intact while supplying that
    # shared minimum valid fixture section.
    if "[ram_layout]" in config or config.count("[functions]") != 1:
        raise ValueError("synthetic configs must have one functions table and no ram_layout")
    config = config.replace("[functions]", "[ram_layout]\n\n[functions]", 1)
    case_dir, output_dir = write_case(root, name, rom, config)
    status, log = run_generator(exe, case_dir, output_dir)
    return case_dir, output_dir, status, log


def valid_alias_rom() -> bytes:
    # MOVEQ at $1F68, ten NOPs, then the real six-byte JMP at $1F7E -> $1DFE.
    parent = bytes.fromhex("70 01") + bytes.fromhex("4E 71") * 10
    parent += bytes.fromhex("4E F9 00 00 1D FE")
    return rom_image(0x001F68, [(0x001F68, parent),
                                (0x001DFE, bytes.fromhex("4E 75"))])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recompiler", required=True, type=pathlib.Path)
    parser.add_argument("--work-dir", required=True, type=pathlib.Path)
    parser.add_argument("--actual-rom", type=pathlib.Path)
    parser.add_argument("--game-config", type=pathlib.Path)
    args = parser.parse_args()
    exe = args.recompiler.resolve()
    root = args.work_dir.resolve()
    require(exe.is_file(), f"recompiler executable not found: {exe}")
    root.mkdir(parents=True, exist_ok=True)

    # Explicit alias: check both entry wrappers, exact-label transfer, PC trace,
    # and that the JMP suffix neither pushes a guest return nor writes A7.
    config = (
        '[game]\noutput_prefix = "interior_alias_fixture"\n'
        "[functions]\nextra = [0x001DFE]\n"
        + alias_table(0x001F7E, 0x001F68)
    )
    case, out, status, log = run_case(
        exe, root, "explicit-alias", valid_alias_rom(), config)
    require(status == 0, f"explicit alias generation failed; evidence: {case}")
    src = generated_source(out)
    dispatch = (out / "interior_alias_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    body_match = re.search(
        r"void func_body_001F68\(uint32_t _entry\) \{(.*?)\n\}\n\n"
        r"void func_001F68\(void\)", src, re.S)
    require(body_match is not None, f"shared owner body/wrapper missing; evidence: {case}")
    body = body_match.group(1)
    require("case 0x001F7Eu: goto label_001F7E;" in body,
            f"alias does not jump to its exact instruction label; evidence: {case}")
    require("func_body_001F68(0x001F68u)" in src and
            "func_body_001F68(0x001F7Eu)" in src,
            f"parent and alias are not wrappers over one body; evidence: {case}")
    require("func_001F7E" in dispatch,
            f"alias missing from generated dispatch; evidence: {case}")
    switch_at = body.index("switch (_entry)")
    parent_insn_at = body.index("rdb_on_insn(0x001F68u)")
    alias_label_at = body.index("label_001F7E:;")
    alias_insn_at = body.index("rdb_on_insn(0x001F7Eu)")
    require(switch_at < parent_insn_at < alias_label_at < alias_insn_at,
            f"dispatch/parent/alias instruction order is wrong; evidence: {case}")
    require("recomp_tail_call(0x001DFEu); return;" in body[alias_label_at:],
            f"$001F7E no longer JMP-dispatches to $001DFE; evidence: {case}")
    require("recomp_push_return" not in body[alias_label_at:] and
            not re.search(r"g_cpu\.A\[7\]\s*(?:\+\+|--|[+\-]?=)", body),
            f"alias wrapper/JMP suffix changes guest A7 or pushes a return; evidence: {case}")
    prologue = body[:switch_at]
    require(not re.search(r"\b_(?:ts|sv|fv|sp_popped)\w*\s*=|g_cpu\.[DA]\[\d\]\s*=",
                          prologue),
            f"shared-body prologue initializes guest-dependent locals before alias dispatch; evidence: {case}")
    print("PASS explicit alias and normal parent entry share one body; alias starts at $001F7E and tail-dispatches to $001DFE")

    # The Round 2 neutral-flight experiment's existing alias remains an exact
    # shared-body entry. Keep it in the same generator-only regression suite.
    boss_alias_rom = rom_image(0x02C224, [
        (0x02C224, bytes.fromhex("70 01 4E 71 4E 71 70 02 4E 75")),
    ])
    boss_alias_config = (
        '[game]\noutput_prefix = "boss_alias_fixture"\n'
        "[functions]\nextra = [0x02C224]\n"
        + alias_table(0x02C22A, 0x02C224)
    )
    case, out, status, log = run_case(
        exe, root, "existing-boss-alias", boss_alias_rom, boss_alias_config)
    require(status == 0, f"$02C22A alias generation failed; evidence: {case}")
    src = generated_source(out)
    dispatch = (out / "boss_alias_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    require("case 0x02C22Au: goto label_02C22A;" in src and
            "func_body_02C224(0x02C22Au)" in src and
            "func_02C22A" in dispatch,
            f"existing $02C22A alias no longer enters its exact shared-body label; evidence: {case}")
    print("PASS existing $02C22A alias remains an exact shared-body entry")

    # Explicitly documented producer edges join exact local instruction labels
    # into the shared body. Other selector values retain the hybrid fallback.
    computed_rom = rom_image(0x000400, [
        (0x000400, bytes.fromhex("70 00 10 15 E3 48 4E FB 00 02")),
        (0x00040A, bytes.fromhex("4E 71 4E 71 4E 75")),
        (0x000410, bytes.fromhex("4E 75")),
    ])
    computed_config = (
        '[game]\noutput_prefix = "computed_jump_fixture"\n'
        "[functions]\nextra = [0x000400, 0x000410]\n"
        + alias_table(0x00040A, 0x000400, 0x000406)
        + alias_table(0x00040C, 0x000400, 0x000406)
    )
    case, out, status, log = run_case(
        exe, root, "computed-in-function", computed_rom, computed_config)
    require(status == 0, f"verified computed-jump generation failed; evidence: {case}")
    src = generated_source(out)
    dispatch = (out / "computed_jump_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    body_match = re.search(
        r"void func_body_000400\(uint32_t _entry\) \{(.*?)\n\}\n\n"
        r"void func_000400\(void\)", src, re.S)
    require(body_match is not None,
            f"computed-jump host body missing; evidence: {case}")
    body = body_match.group(1)
    require("case 0: goto label_00040A;" in body and
            "case 2: goto label_00040C;" in body,
            f"computed jump does not branch to exact decoded target labels; evidence: {case}")
    require("default:\n      hybrid_jmp_interpret(0x0000040Au +" in body,
            f"unrecognized computed destination lost its interpreter fallback; evidence: {case}")
    require("func_000400" in dispatch and "func_00040A" in dispatch and
            "func_00040C" in dispatch and "func_000410" in dispatch,
            f"normal root dispatch entries changed; evidence: {case}")
    switch = body[body.index("switch ((int32_t)m68k_brief_index_value"):]
    switch = switch[:switch.index("\n  }")]
    require("recomp_push_return" not in switch and "g_cpu.A[7]" not in switch and
            "g_cpu.SR =" not in switch,
            f"computed-jump switch alters guest stack or condition codes; evidence: {case}")
    print("PASS PC-indexed jump maps multiple verified local PCs, preserves guest state in the switch, and falls back for other targets")

    # A discovered root inside the mathematical target range is not enough to
    # prove a local computed edge. Without a producer declaration, retain the
    # hybrid fallback and the ordinary function entry.
    bounded_jump_rom = rom_image(0x000600, [
        (0x000600, bytes.fromhex("70 00 10 15 E3 48 4E FB 00 00")),
        (0x000620, bytes.fromhex("70 01 4E 71 4E 71 70 02 4E 75")),
    ])
    bounded_jump_config = (
        '[game]\noutput_prefix = "bounded_jump_fixture"\n'
        "[functions]\nextra = [0x000600, 0x000620]\n"
    )
    case, out, status, log = run_case(
        exe, root, "bounded-computed-root", bounded_jump_rom,
        bounded_jump_config)
    require(status == 0, f"bounded computed-jump generation failed; evidence: {case}")
    src = generated_source(out)
    dispatch = (out / "bounded_jump_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    body_match = re.search(
        r"void func_000600\(void\) \{(.*?)\n\}", src, re.S)
    require(body_match is not None,
            f"bounded computed-jump host body missing; evidence: {case}")
    body = body_match.group(1)
    require("case 32: goto label_000628;" not in body and
            "case 4: goto label_000610;" not in body and
            "hybrid_jmp_interpret(0x00000608u +" in body,
            f"computed jump promoted a discovered root without producer evidence; evidence: {case}")
    require("func_000620" in dispatch and "void func_000620(void)" in src,
            f"ordinary dispatch entry for the sparse target root changed; evidence: {case}")
    print("PASS discovered roots alone do not create computed aliases; ordinary entry and hybrid fallback remain")

    # A word in an instruction extension may itself decode as a legal opcode.
    # Keep the earlier decoded instruction authoritative and reject the
    # overlapping discovered root as a local computed-jump destination.
    overlap_rom = rom_image(0x000700, [
        # A negative PC displacement places the computed target base just
        # before this function. No producer declaration is present, so even
        # legal-looking roots remain ordinary entries, not local jump cases.
        (0x000700, bytes.fromhex("70 00 10 15 E3 48 4E FB 00 F6")),
        (0x000720, bytes.fromhex("10 3C 70 00 4E 75")),
    ])
    overlap_config = (
        '[game]\noutput_prefix = "overlap_jump_fixture"\n'
        "[functions]\nextra = [0x000700, 0x000720, 0x000722]\n"
    )
    case, out, status, log = run_case(
        exe, root, "computed-overlap-rejected", overlap_rom, overlap_config)
    require(status == 0, f"overlapping computed-root generation failed; evidence: {case}")
    src = generated_source(out)
    body_match = re.search(
        r"void func_000700\(void\) \{(.*?)\n\}", src, re.S)
    require(body_match is not None,
            f"overlap computed-jump host body missing; evidence: {case}")
    body = body_match.group(1)
    require("case 34: goto label_000720;" not in body and
            "case 36: goto label_000722;" not in body and
            "hybrid_jmp_interpret(0x000006FEu +" in body,
            f"unproven computed roots were promoted to local dispatch; evidence: {case}")
    print("PASS unproven computed roots keep ordinary entries and use hybrid fallback")

    # A computed index that lands outside the exact decoded body must not be
    # promoted to a local label. The same switch keeps the original hybrid
    # fallback for that unrecognized destination (D0=4 -> $00050C).
    unrecognized_rom = rom_image(0x000500, [
        (0x000500, bytes.fromhex("70 00 4E FB 00 04 4E 71 4E 71 4E 75")),
    ])
    unrecognized_config = (
        '[game]\noutput_prefix = "unrecognized_jump_fixture"\n'
        "[functions]\nextra = [0x000500]\n"
    )
    case, out, status, log = run_case(
        exe, root, "computed-unrecognized", unrecognized_rom,
        unrecognized_config)
    require(status == 0, f"unrecognized computed-jump generation failed; evidence: {case}")
    src = generated_source(out)
    require("hybrid_jmp_interpret(0x00000508u +" in src and
            "case 4: goto label_00050C;" not in src,
            f"unrecognized target was silently accepted as a local label; evidence: {case}")
    print("PASS out-of-body computed destination has no local case and retains hybrid fallback")

    # Known function roots are not enough to prove an arbitrary computed
    # selector is an in-function jump table. Keep those entries reachable
    # through the ordinary hybrid dispatcher when the selector pattern is
    # unrecognized.
    unproven_root_rom = rom_image(0x000520, [
        (0x000520, bytes.fromhex("30 15 4E FB 00 04 4E 71 4E 75 4E 75")),
    ])
    unproven_root_config = (
        '[game]\noutput_prefix = "unproven_root_fixture"\n'
        "[functions]\nextra = [0x000520, 0x000528, 0x00052A]\n"
    )
    case, out, status, log = run_case(
        exe, root, "unproven-computed-root", unproven_root_rom,
        unproven_root_config)
    require(status == 0,
            f"unproven computed-root generation failed; evidence: {case}")
    src = generated_source(out)
    dispatch = (out / "unproven_root_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    body_match = re.search(
        r"void func_000520\(void\) \{(.*?)\n\}", src, re.S)
    require(body_match is not None,
            f"unproven computed-jump host body missing; evidence: {case}")
    body = body_match.group(1)
    require("hybrid_jmp_interpret(0x00000528u +" in body and
            "case 0: goto label_000528;" not in body and
            "case 2: goto label_00052A;" not in body,
            f"unproven selector promoted discovered roots to local labels; evidence: {case}")
    require("func_000528" in dispatch and "func_00052A" in dispatch,
            f"hybrid fallback lost ordinary function-entry dispatch; evidence: {case}")
    print("PASS unproven selector retains hybrid dispatch to discovered function entries")

    # If the containing body carries split-stack accounting, an unrecognized
    # computed destination must take the same stack-delta handoff as the
    # previous hybrid-JMP emitter before returning to the interpreter.
    stack_fallback_rom = rom_image(0x000540, [
        (0x00054E, bytes([0xFF]) * 0x200),
        (0x000540, bytes.fromhex("48 79 00 00 06 00 70 00 10 15 E3 48 4E FB 00 00")),
        (0x000560, bytes.fromhex("4A FC")),
    ])
    stack_fallback_config = (
        '[game]\noutput_prefix = "stack_fallback_fixture"\n'
        "[functions]\nextra = [0x000540]\n"
        + alias_table(0x000560, 0x000540, 0x00054C)
    )
    case, out, status, log = run_case(
        exe, root, "computed-fallback-stack-state", stack_fallback_rom,
        stack_fallback_config)
    require(status == 0,
            f"stack-aware computed fallback generation failed; evidence: {case}")
    src = generated_source(out)
    require("case 18: goto label_000560;" in src and
            "default:\n      g_split_sp_popped += _sp_popped; _sp_popped = 0;\n"
            "      hybrid_jmp_interpret(0x0000054Eu +" in src,
            f"computed-JMP fallback did not preserve split-stack state; evidence: {case}")
    print("PASS verified local target and unrecognized fallback preserve split-stack handoff")

    # An operand word that happens to decode as RTS must still be rejected.
    operand_rom = rom_image(0x001F68, [
        (0x001F68, bytes.fromhex("30 3C 4E 75 4E 75")),
    ])
    bad_config = ('[game]\noutput_prefix = "bad_operand"\n[functions]\n' +
                  alias_table(0x001F6A, 0x001F68))
    case, out, status, log = run_case(exe, root, "invalid-operand", operand_rom, bad_config)
    require(status != 0 and "interior alias $001F6A -> $001F68 rejected" in log,
            f"operand-word alias was not rejected explicitly; evidence: {case}")
    print("PASS invalid operand-word declaration rejected")

    # A legal instruction boundary outside the owner's CFG is not an alias.
    unreachable_rom = rom_image(0x001F68, [
        (0x001F68, bytes.fromhex("4E 75")),
        (0x001F7E, bytes.fromhex("4E 75")),
    ])
    bad_config = ('[game]\noutput_prefix = "bad_owner"\n[functions]\n' +
                  alias_table(0x001F7E, 0x001F68))
    case, out, status, log = run_case(exe, root, "invalid-owner", unreachable_rom, bad_config)
    require(status != 0 and "owner CFG does not reach" in log,
            f"unreachable owner declaration was not rejected; evidence: {case}")
    print("PASS invalid owner relationship rejected")

    # Repeated declarations are ambiguous even when both name the same owner.
    duplicate_config = (
        '[game]\noutput_prefix = "duplicate_alias"\n[functions]\nextra = [0x001DFE]\n'
        + alias_table(0x001F7E, 0x001F68)
        + alias_table(0x001F7E, 0x001F68)
    )
    case, out, status, log = run_case(
        exe, root, "invalid-duplicate", valid_alias_rom(), duplicate_config)
    require(status != 0 and "more than one alias declaration" in log,
            f"duplicate alias declaration was not rejected; evidence: {case}")
    print("PASS duplicate alias declaration rejected")

    # Explicit computed-edge provenance admits only the declared PCs from the
    # named producer. The first jump models FF -> an interior handler; the
    # nested jump models selector 01 -> a BRA.W continuation.
    rooted_jump_rom = rom_image(0x000400, [
        (0x000400, bytes.fromhex(
            "70 00 10 3C 00 FF 04 00 00 E0 E5 48 4E FB 00 02")),
        # Do not leave zero-filled ORI instructions at the target base; that
        # would create an artificial offset-table edge into the alias stream.
        (0x000410, bytes.fromhex("4A FC")),
        (0x00048C, bytes.fromhex("70 00 10 1C E5 48 4E FB 00 02")),
        (0x00049A, bytes.fromhex("60 00 45 74")),
        (0x0004A10, bytes.fromhex("12 1C 4E 75")),
    ])
    rooted_jump_config = (
        '[game]\noutput_prefix = "rooted_jump_fixture"\n'
        "[functions]\nextra = [0x000400, 0x0004A10]\n"
        + alias_table(0x00048C, 0x000400, 0x00040C)
        + alias_table(0x00049A, 0x000400, 0x000492)
    )
    case, out, status, log = run_case(
        exe, root, "rooted-computed-edges", rooted_jump_rom,
        rooted_jump_config)
    require(status == 0,
            f"proven computed-edge generation failed; evidence: {case}")
    src = generated_source(out)
    dispatch = (out / "rooted_jump_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    body_match = re.search(
        r"void func_body_000400\(uint32_t _entry\) \{(.*?)\n\}\n\n"
        r"void func_000400\(void\)", src, re.S)
    require(body_match is not None,
            f"computed-edge shared body missing; evidence: {case}")
    body = body_match.group(1)
    require("case 124: goto label_00048C;" in body and
            "case 4: goto label_00049A;" in body,
            f"outer/nested selector targets are not exact local labels; evidence: {case}")
    require("default:\n      hybrid_jmp_interpret(0x00000410u +" in body and
            "default:\n      hybrid_jmp_interpret(0x00000496u +" in body,
            f"unrecognized computed targets lost their existing fallback; evidence: {case}")
    require("recomp_tail_call(0x004A10u); return;" in body,
            f"nested BRA.W did not continue to its exact guest destination; evidence: {case}")
    alias_at = body.index("label_00049A:;")
    prior_instruction_at = body.index("rdb_on_insn(0x00048Cu)")
    alias_instruction_at = body.index("rdb_on_insn(0x00049Au)")
    require(prior_instruction_at < alias_at < alias_instruction_at,
            f"nested direct entry does not bypass earlier instructions; evidence: {case}")
    require("func_body_000400(0x00048Cu)" in src and
            "func_body_000400(0x00049Au)" in src and
            "func_00048C" in dispatch and "func_00049A" in dispatch,
            f"computed targets lost shared-body dispatch wrappers; evidence: {case}")
    switches = re.findall(
        r"switch \(\(int32_t\)m68k_brief_index_value.*?\n  \}", body, re.S)
    require(len(switches) >= 2 and all(
        "recomp_push_return" not in block and "g_cpu.A[7]" not in block and
        "g_cpu.SR =" not in block for block in switches),
        f"computed-jump switches alter guest registers, A7, or CCR; evidence: {case}")
    print("PASS outer and nested computed targets use exact labels, preserve state, continue through BRA.W, and retain fallbacks")

    # A representable computed target is still rejected if it overlaps the
    # immediate word of another reachable instruction.
    bad_jump_rom = rom_image(0x000600, [
        (0x000600, bytes.fromhex("10 3C 00 4E 4E FB 00 02 4E 75")),
    ])
    bad_jump_config = (
        '[game]\noutput_prefix = "bad_jump_operand"\n'
        "[functions]\nextra = [0x000600]\n"
        + alias_table(0x000602, 0x000600, 0x000604)
    )
    case, out, status, log = run_case(
        exe, root, "invalid-computed-operand", bad_jump_rom,
        bad_jump_config)
    require(status != 0 and "overlaps operand bytes" in log,
            f"computed alias into an operand was not rejected; evidence: {case}")
    print("PASS computed alias into a reachable instruction operand rejected")

    # Existing branch-proven alias behavior remains governed by its old opt-in.
    branch_rom = rom_image(0x000200, [
        (0x000200, bytes.fromhex("66 06 4E 75 4E 71 4E 71 74 03 4E 75")),
    ])
    branch_config = (
        '[game]\noutput_prefix = "branch_alias_fixture"\nfunction_aliases = true\n'
        '[functions]\nextra = [0x000200, 0x000208]\n'
    )
    case, out, status, log = run_case(
        exe, root, "branch-proven", branch_rom, branch_config)
    require(status == 0, f"branch-proven alias generation failed; evidence: {case}")
    src = generated_source(out)
    dispatch = (out / "branch_alias_fixture_dispatch.c").read_text(
        encoding="utf-8", errors="replace")
    require("case 0x000208u: goto label_000208;" in src and
            "func_body_000200(0x000208u)" in src and
            "func_000208" in dispatch,
            f"existing branch-proven shared-body alias behavior changed; evidence: {case}")
    print("PASS existing branch-proven alias behavior retained")

    # Actual-ROM generation is part of the focused test. This catches a
    # synthetic heuristic pass that still leaves the authentic subtract/shift
    # dispatch at $06A7AE on the hybrid path.
    if args.actual_rom or args.game_config:
        require(args.actual_rom is not None and args.game_config is not None,
                "--actual-rom and --game-config must be supplied together")
        actual_rom = args.actual_rom.resolve()
        actual_config = args.game_config.resolve()
        require(actual_rom.is_file(), f"actual ROM not found: {actual_rom}")
        require(actual_config.is_file(), f"actual game config not found: {actual_config}")
        rom_data = actual_rom.read_bytes()
        require(hashlib.sha256(rom_data).hexdigest().upper() == ROM_SHA256,
                "unsupported ROM; use the validated Shinobi III revision")
        config_text = actual_config.read_text(encoding="utf-8")
        # Supported-ROM digest and generated-code checks cover this path.
        require("entry = 0x06A82E" in config_text and
                "owner = 0x06A7A8" in config_text and
                "jump = 0x06A7AE" in config_text and
                "entry = 0x06A83C" in config_text and
                "jump = 0x06A834" in config_text,
                "game config does not opt in both ROM-proven FF computed edges")
        actual_case, actual_out = write_case(
            root, "actual-shinobi-rom", rom_data, config_text)
        status, log = run_generator(exe, actual_case, actual_out)
        require(status == 0,
                f"actual Shinobi III code generation failed; evidence: {actual_case}")

        owner_body = None
        part_texts = []
        for part in sorted(actual_out.glob("*_part*.c")):
            part_text = part.read_text(encoding="utf-8", errors="replace")
            part_texts.append(part_text)
            owner_pos = part_text.find("void func_body_06A7A8(uint32_t _entry)")
            if owner_pos >= 0:
                owner_end = part_text.find("\nvoid func_", owner_pos + 1)
                owner_body = part_text[owner_pos:owner_end if owner_end >= 0 else None]
        require(owner_body is not None,
                f"actual-ROM shared owner body missing; evidence: {actual_case}")
        require("case 124: goto label_06A82E;" in owner_body and
                "case 4: goto label_06A83C;" in owner_body,
                f"actual FF outer/nested dispatch lacks exact local labels; evidence: {actual_case}")
        actual_text = "\n".join(part_texts)
        require("func_body_06A7A8(0x06A7A8u)" in actual_text and
                "func_body_06A7A8(0x06A82Eu)" in actual_text and
                "func_body_06A7A8(0x06A83Cu)" in actual_text and
                "recomp_tail_call(0x06AC4Eu); return;" in owner_body,
                f"actual shared wrappers or $06AC4E continuation changed; evidence: {actual_case}")
        switch_pos = owner_body.find("switch (_entry)")
        parent_pc_pos = owner_body.find("rdb_on_insn(0x06A7A8u)")
        outer_label_pos = owner_body.find("label_06A82E:;")
        outer_pc_pos = owner_body.find("rdb_on_insn(0x06A82Eu)")
        require(0 <= switch_pos < parent_pc_pos < outer_label_pos < outer_pc_pos,
                f"direct $06A82E wrapper does not enter after parent instructions; evidence: {actual_case}")
        require(re.search(
            r"m68k_read8\(g_cpu\.A\[4\]\); g_cpu\.A\[4\] \+= 1", owner_body),
                f"actual FF handler lost the subcommand cursor increment; evidence: {actual_case}")

        # Verify both sound indexed-jump bases and rooted indices. These paths
        # stay on their existing function-entry/fallback handling; no high
        # selector destinations are promoted by this patch.
        sound_cases = {
            0x069BB0: (0x0002, 0x069BB4, (0x069BB4, 0x069BB6, 0x069BBA)),
            0x069BCA: (0x0002, 0x069BCE, (0x069BCE, 0x069BD0, 0x069BD4)),
        }
        for producer, (ext, base, destinations) in sound_cases.items():
            # Supported-ROM digest and generated-code checks cover this path.
            for selector, destination in zip((0, 1, 3), destinations):
                require(base + 2 * selector == destination,
                        f"sound selector {selector} maps incorrectly at ${producer:06X}")
                require(any(f"func_{destination:06X}" in text for text in part_texts),
                        f"rooted sound destination ${destination:06X} was lost")
        sound_text = "\n".join(part_texts)
        require("hybrid_jmp_interpret(0x00069BB4u + m68k_brief_index_value(0x0002u" in sound_text and
                "hybrid_jmp_interpret(0x00069BCEu + m68k_brief_index_value(0x0002u" in sound_text,
                "sound computed-jump fallback/base semantics unexpectedly changed")
        alias_entries = set(re.findall(
            r"\[\[functions\.interior_alias\]\]\s*entry\s*=\s*0x([0-9A-Fa-f]+)",
            config_text))
        unresolved_sound_targets = {"069C3A", "069C56", "069C60", "069C82", "069CBA"}
        require(not (alias_entries & unresolved_sound_targets),
                "an unresolved high sound selector was promoted to an alias")
        print("PASS actual Shinobi ROM outer/nested FF path and $069BB0/$069BCA selector bases; unresolved sound targets remain unaliased")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
