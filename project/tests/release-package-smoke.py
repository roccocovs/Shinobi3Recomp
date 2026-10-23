#!/usr/bin/env python3
"""Inspect the built Windows executable and its packaged DLLs without running it."""
import argparse
from pathlib import Path
import struct


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_pe(path: Path) -> tuple[int, set[str]]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("missing DOS signature")
    pe = u32(data, 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("missing PE signature")
    file_header = pe + 4
    sections_count = u16(data, file_header + 2)
    optional_size = u16(data, file_header + 16)
    optional = file_header + 20
    if u16(data, optional) != 0x20B:
        raise ValueError("expected a 64-bit PE32+ executable")
    subsystem = u16(data, optional + 68)
    import_directory = optional + 112 + 8
    import_rva = u32(data, import_directory)
    section_table = optional + optional_size
    sections = []
    for i in range(sections_count):
        at = section_table + i * 40
        sections.append((u32(data, at + 12), u32(data, at + 8),
                         u32(data, at + 16), u32(data, at + 20)))

    def rva_offset(rva: int) -> int:
        for va, virtual_size, raw_size, raw_at in sections:
            if va <= rva < va + max(virtual_size, raw_size):
                return raw_at + rva - va
        raise ValueError(f"RVA 0x{rva:x} is outside all PE sections")

    def cstring(at: int) -> str:
        end = data.index(b"\0", at)
        return data[at:end].decode("ascii", errors="strict")

    imports = set()
    if import_rva:
        at = rva_offset(import_rva)
        while at + 20 <= len(data):
            descriptor = struct.unpack_from("<IIIII", data, at)
            if not any(descriptor):
                break
            imports.add(cstring(rva_offset(descriptor[3])).lower())
            at += 20
    return subsystem, imports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()
    if not args.exe.is_file():
        raise SystemExit(f"FAIL: executable missing: {args.exe}")
    sdl = args.package / "SDL2.dll"
    if not sdl.is_file():
        raise SystemExit("FAIL: SDL2.dll missing from the app package")
    subsystem, imports = parse_pe(args.exe)
    if subsystem != 2:
        raise SystemExit(f"FAIL: PE subsystem is {subsystem}, expected Windows GUI (2)")

    def is_windows_system_dll(name: str) -> bool:
        return name in {
        "advapi32.dll", "bcrypt.dll", "comdlg32.dll", "gdi32.dll",
        "imm32.dll", "kernel32.dll", "msvcrt.dll", "ntdll.dll",
        "ole32.dll", "oleaut32.dll", "setupapi.dll", "shell32.dll",
        "user32.dll", "version.dll", "winmm.dll", "ws2_32.dll",
        } or name.startswith(("api-ms-win-", "ext-ms-win-"))

    sdl_subsystem, sdl_imports = parse_pe(sdl)
    del sdl_subsystem  # SDL2 is a DLL; only its dependencies matter here.
    unexpected = {name for name in sdl_imports if not is_windows_system_dll(name)}
    non_system = {name for name in imports if not is_windows_system_dll(name)}
    if non_system != {"sdl2.dll"} or unexpected:
        raise SystemExit(
            "FAIL: unexpected runtime dependencies: "
            f"app={sorted(non_system)}, SDL2={sorted(unexpected)}")

    forbidden_rom = [path for path in args.package.rglob("*")
                     if path.is_file() and path.name.lower() == "shinobi3.gen"]
    if forbidden_rom:
        raise SystemExit(f"FAIL: original ROM must not be packaged: {forbidden_rom[0]}")
    rom_extensions = {".gen", ".rom", ".smd"}
    unexpected_game_files = [path for path in args.package.rglob("*")
                             if path.is_file() and path.suffix.lower() in rom_extensions]
    if unexpected_game_files:
        raise SystemExit(f"FAIL: game ROM data must not be packaged: {unexpected_game_files[0]}")

    print("PASS: 64-bit Windows GUI executable; SDL2.dll is the only bundled runtime DLL dependency.")
    print("System imports: " + ", ".join(sorted(imports - non_system)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
