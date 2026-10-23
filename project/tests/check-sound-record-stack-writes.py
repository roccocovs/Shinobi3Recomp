"""Reject guest stack writes into the special-SFX record in a boot write log.

Run with --mem-write-log 0xFFFB70-0xFFFB9F@32000. This checks recorded
addresses and registers, independently of the last-function diagnostic label.
"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = hits = 0
    examples = []
    for line in args.trace.open(errors='replace'):
        fields = line.split()
        if len(fields) < 14 or not fields[0].isdigit():
            continue
        records += 1
        frame, address, sp = int(fields[0]), int(fields[3], 16), int(fields[5], 16)
        # Ignore only reset clearing. Never ignore later corruption.
        if frame > 0 and 0xFFFB70 <= address <= 0xFFFB9F and 0xFFF700 <= sp <= 0xFFFC00:
            hits += 1
            if len(examples) < 8:
                examples.append({'frame': frame, 'address': hex(address),
                                 'stack_pointer': hex(sp), 'function': fields[12]})
    result = {'records': records, 'stack_region_write_hits': hits,
              'examples': examples, 'passed': records > 0 and hits == 0}
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != 'examples'}))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
