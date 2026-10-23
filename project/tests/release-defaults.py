#!/usr/bin/env python3
"""Guard the public build's native-first and six-button defaults."""
import argparse
from pathlib import Path
import re


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--glue", required=True, type=Path)
    parser.add_argument("--controller-test", required=True, type=Path)
    parser.add_argument("--main", required=True, type=Path)
    parser.add_argument("--change-rom-helper", required=True, type=Path)
    args = parser.parse_args()

    spec = args.spec.read_text(encoding="utf-8")
    glue = args.glue.read_text(encoding="utf-8")
    controller_test = args.controller_test.read_text(encoding="utf-8")
    main = args.main.read_text(encoding="utf-8")
    change_rom_helper = args.change_rom_helper.read_text(encoding="utf-8")
    checks = {
        "interpreter floor defaults off": ".tier3_floor_default = 0" in spec,
        "whole-program interpreter is opt-in":
            "v = (e && *e && *e != '0') ? 1 : 0;" in glue,
        "six-button profile is the absent-variable default":
            "return !value ||" in spec and 'strcmp(value, "off") != 0' in spec,
        "controller test clears override before asserting default":
            'GENESIS_SHINOBI_EXPERT_CONTROLS", ""' in controller_test,
        "interpreter-floor override remains available":
            'getenv("GENESIS_FLOOR")' in glue,
        "interpreter override remains available":
            'getenv("GENESIS_FORCE_INTERP")' in glue,
        "double-click can request the ROM picker":
            'strcmp(argv[i], "--select-rom") == 0' in main,
        "remembered ROM is stored under Local AppData":
            'GetEnvironmentVariableA("LOCALAPPDATA"' in main and
            '"%s\\\\Shinobi3Recomp"' in main and
            '"%s\\\\rom-Shinobi3.cfg"' in main,
        "Windows config does not fall back beside the executable":
            bool(re.search(r"#ifdef _WIN32\s+report_startup_error\(\"Configuration unavailable\".*?return 1;\s+#else\s+.*?exe_relative\(\"rom-Shinobi3.cfg\"\)", main, re.S)),
        "double-click ROM-change helper uses the supported picker path":
            '" --select-rom"' in change_rom_helper,
        "ROM selection is skipped for an explicit positional argument":
            "explicit_path && explicit_path[0]" in args.main.parent.joinpath("rom_selection.c").read_text(encoding="utf-8"),
    }
    failures = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
