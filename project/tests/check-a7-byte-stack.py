"""Reject the startup stack leak using the real ROM and generated instruction.

This checks the actual $006E74 translation, not a simulated replacement.
Follow with a cold-boot replay using GENESIS_STRICT_JSR_STACK=1.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--generated', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    assert hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256, "wrong ROM"
    matches = []
    for path in args.generated.glob('shinobi3_part*.c'):
        text = path.read_text()
        marker = '/* $006E74 */'
        if marker in text:
            block = text.split(marker, 1)[1].split('/* $006E76 */', 1)[0]
            step = re.search(r'm68k_read8\(g_cpu\.A\[7\]\).*?'
                             r'g_cpu\.A\[7\] \+= (\d+);', block, re.S)
            assert step, 'Missing byte read at the ROM instruction'
            matches.append((str(path), int(step.group(1))))
    assert len(matches) == 1, 'Expected exactly one startup instruction'
    path, increment = matches[0]
    result = {'instruction': '006E74', 'generated_file': path,
              'observed_increment': increment, 'expected_increment': 2,
              'loop_iterations': 128 * 8,
              'net_stack_change': (increment - 2) * 128 * 8,
              'passed': increment == 2}
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
