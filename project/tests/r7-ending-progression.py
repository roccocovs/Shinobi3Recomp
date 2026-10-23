#!/usr/bin/env python3
"""Execute generated ending fragments in an isolated synthetic CPU fixture.

No game, interpreter, emulator, renderer, audio device, or persistent save is
started. Allocation and random vectors are fixture inputs. Scene branches,
actor setup/animation, movement arithmetic, and stack returns are generated C.
"""
import argparse
import hashlib
import importlib.util
import re
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rom', type=Path, required=True)
    p.add_argument('--generated-dir', type=Path, required=True)
    p.add_argument('--runtime-include', type=Path, required=True)
    p.add_argument('--cc', required=True)
    p.add_argument('--work-dir', type=Path, required=True)
    a = p.parse_args()
    module_spec = importlib.util.spec_from_file_location(
        'ending_static', Path(__file__).with_name('r7-final-boss-execution.py'))
    m = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(m)
    rom = a.rom.read_bytes()
    m.require(hashlib.sha256(rom).hexdigest().upper() == m.ROM_SHA256, 'wrong ROM')
    # These are the actual ending's state table and predecessor of the crash
    # actor. $0069A8 is installed only at the end of this timeline.
    targets = (0x10458,0x1053A,0x10548,0x10568,0x1058A,0x105BE,
               0x114B8,0x11502,0x11542,0x1061C,0x106CC,0x106E2,
               0x106F8,0x1071A,0x10752,0x10768,0x1079E,0x107BA,0x109D0)
    dispatch = (a.generated_dir / 'shinobi3_dispatch.c').read_text()
    for i, target in enumerate(targets):
        veneer = 0x103EA + 4*i
        opcode = int.from_bytes(rom[veneer:veneer+2], 'big')
        m.require((opcode >> 8) == 0x60 and (opcode & 0xFF) == 0 and
                  veneer+2+int.from_bytes(rom[veneer+2:veneer+4], 'big', signed=True) == target,
                  'ending timeline branch changed')
        m.require(m.dispatch_entry(dispatch, veneer) and m.dispatch_entry(dispatch,target),
                  f'ending timeline lacks native ${veneer:06X}->${target:06X}')
    # Supported-ROM digest and generated-code checks cover this path.
    m.require(m.dispatch_entry(dispatch,0x10A02), 'ending HBlank callback $010A02 missing')
    # Supported-ROM digest and generated-code checks cover this path.
    # Caption/credits frames advance by the ROM script's $FF00F6 index;
    # a negative offset marks completion in $FF00FA, consumed by $011502.
    for addr, needles in {
        0x1155E: ('0x00FF00F6', '0x00FF00FA', '0x00410Au'),
        0x11502: ('0x00FF00FA', '0x00FF0034'),
        0x107BA: ('0x000069A8u', '0x00FF0032'),
    }.items():
        b = m.body(a.generated_dir, addr)
        m.require(all(n in b for n in needles), f'ending continuation ${addr:06X} changed')
    # Only fragments used by the fixture below are linked. Device work is
    # bounded and recorded; no production runtime is booted.
    selected = [0x10548,0x10568,0x107FC,0x107F2,0x107E6,0x107EA,0x107EE,
                0x1083A,0x1083C,0x108CA,0x1090A,0x10946,0x10948,0x10976,
                0x109B2,0x109D0,0x109E8,0x10A26,0x10A4C,0x10A60,
                0x3670C,0x1DDB2,0x178E,0x19D4,0x10A02]
    for addr in selected:
        m.require(m.dispatch_entry(dispatch,addr), f'native fragment ${addr:06X} missing')
    bodies = '\n'.join(m.body(a.generated_dir,addr) for addr in selected)
    fixture = Path(__file__).with_name('r7-ending-progression-harness.c').read_text()
    declarations = '\n'.join(f'void func_{addr:06X}(void);' for addr in selected)
    table = '\n'.join(f'case 0x{addr:06X}: return func_{addr:06X};' for addr in selected)
    fixture = fixture.replace('/* GENERATED_DECLARATIONS */', declarations)
    fixture = fixture.replace('/* GENERATED_LOOKUP */', table)
    fixture += '\n' + bodies
    a.work_dir.mkdir(parents=True, exist_ok=True)
    source = a.work_dir / 'r7-ending-fragments.c'
    exe = a.work_dir / 'R7EndingProgressionHarness.exe'
    source.write_text(fixture)
    # Remove the previous test artifact so a failed compile cannot run stale code.
    if exe.exists(): exe.unlink()
    subprocess.run([a.cc, '-std=c11', '-O0', '-I'+str(a.runtime_include), str(source),
                    '-o', str(exe)], check=True)
    subprocess.run([str(exe),str(a.rom)], check=True)
    print('PASS: ROM ending timeline, ship spawn/Y completion, credits script and HBlank provenance')
    print('NOTE: fixture does not establish live VBlank/audio pacing or gameplay acceptance')


if __name__ == '__main__':
    main()
