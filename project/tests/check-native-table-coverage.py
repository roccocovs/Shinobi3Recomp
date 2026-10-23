"""Validate the $039DC6 ROM table and optional generated native coverage.

This is a discovery check, not an interpreter parity or live gameplay test.
Pass --generated after regeneration to check both branch entries exist.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--generated', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'test': 'native-table-discovery', 'parity_tested': False}
    try:
        rom = args.rom.read_bytes()
        expected_sha256 = 'E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3'
        result['rom_sha256'] = hashlib.sha256(rom).hexdigest().upper()
        assert result['rom_sha256'] == expected_sha256, 'Unexpected ROM'
        word = lambda a: int.from_bytes(rom[a:a + 2], 'big')
        assert word(0x039DC6) == 0x4EFB and word(0x039DC8) == 2, 'Unexpected indexed JMP'
        assert word(0x039DCA) == 0x6000 and word(0x039DCC) == 4, 'State 0 branch changed'
        assert word(0x039DCE) == 0x60D0, 'State 4 branch changed'
        roots = tomllib.loads(args.config.read_text())['functions']['extra']
        entries = (0x039DCA, 0x039DCE)
        for address in entries:
            assert roots.count(address) == 1, f'Entry {address:06X} absent or duplicated'
        result['configured_entries'] = [f'{a:06X}' for a in entries]
        if args.generated:
            dispatch = (args.generated / 'shinobi3_dispatch.c').read_text()
            bodies = '\n'.join(p.read_text() for p in args.generated.glob('shinobi3_part*.c'))
            for address in (*entries, 0x039DD0):
                assert re.search(r'\{ 0x%06Xu, func_' % address, dispatch), f'No dispatch for {address:06X}'
                assert f'void func_{address:06X}(void)' in bodies, f'No body for {address:06X}'
            assert '0x039DCAu' in bodies and '0x039DCEu' in bodies, 'Missing generated entries'
            result['generated_coverage'] = 'PASS'
        else:
            result['generated_coverage'] = 'PENDING'
        result['status'] = 'PASS'
    except (AssertionError, OSError, KeyError, ValueError) as error:
        result['status'] = 'FAIL'
        result['error'] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f"{result['status']}: discovery check saved to {args.output}; parity not tested")
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
