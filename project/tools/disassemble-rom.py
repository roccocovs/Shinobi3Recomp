"""Read-only, SHA1-checked ROM disassembly and absolute pointer evidence."""
import argparse
import hashlib
from pathlib import Path
import capstone

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rom', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--span', action='append', default=[], help='hex START:END')
    p.add_argument('--pointer', action='append', default=[], help='hex address')
    a = p.parse_args()
    b = a.rom.read_bytes()
    assert hashlib.sha1(b).hexdigest().upper() == '1E07D7998E3048FCFBA4238AE96496460E91B3A5'
    cs = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_000)
    lines = ['ROM SHA1 VERIFIED: 1E07D7998E3048FCFBA4238AE96496460E91B3A5']
    for span in a.span:
        lo, hi = (int(x,16) for x in span.split(':'))
        lines.append('\nSPAN '+span)
        for i in cs.disasm(b[lo:hi], lo):
            lines.append(f'{i.address:06X} {bytes(i.bytes).hex(" "):25} {i.mnemonic:10} {i.op_str}')
    for target in a.pointer:
        n = int(target,16)
        pattern = n.to_bytes(4,'big')
        pos = 0
        lines.append('\nPOINTER '+target)
        while True:
            pos = b.find(pattern,pos)
            if pos < 0: break
            lines.append(f'{pos:06X}: {b[max(0,pos-8):pos+12].hex(" ")}')
            pos += 1
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text('\n'.join(lines)+'\n')
    print('Disassembly saved: '+str(a.output))

if __name__ == '__main__': main()
