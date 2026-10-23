"""Capture cold-boot attract demos without exposing a window or using saves.

Preserves logs, RAM, screenshots, launch settings, and parsed player states.
Run folders must be new; the ROM remains external to every package.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exe', type=Path, required=True)
    p.add_argument('--rom', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--floor', choices=('0', '1'), default='0')
    p.add_argument('--profile', choices=('0', '1'), default='0')
    p.add_argument('--interpreter', choices=('0', '1'), default='0')
    p.add_argument('--first', type=int, default=3900)
    p.add_argument('--last', type=int, default=18500)
    p.add_argument('--interval', type=int, default=8)
    p.add_argument('--timeout', type=int, default=300)
    a = p.parse_args()
    # Resolve inputs before switching the child's working directory to package/.
    a.exe = a.exe.resolve()
    a.rom = a.rom.resolve()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    package = a.output / 'package'
    package.mkdir()
    for name in ('Shinobi3Recomp.exe', 'SDL2.dll'):
        shutil.copy2(a.exe.parent / name, package / name)
    # A local trace server is needed to retain dispatch evidence, no client connects.
    (package / 'debug.ini').write_text('port=4382\n')
    lines = [f'WAIT {a.first-1}']
    for frame in range(a.first, a.last+1, a.interval):
        if frame != a.first:
            lines.append(f'WAIT {a.interval}')
        lines.append(f'DUMP_RAM {a.output / ("ram-%06d.ram" % frame)}')
        if (frame-a.first) % 48 == 0:
            lines.append(f'SCREENSHOT {a.output / ("frame-%06d.png" % frame)}')
    if len(lines) > 4096:
        raise SystemExit('capture exceeds the runner input limit; increase --interval')
    script = a.output / 'cold-demos.input'
    script.write_text('\n'.join(lines)+'\n')
    env = os.environ.copy()
    env.update(GENESIS_FORCE_INTERP=a.interpreter, GENESIS_FLOOR=a.floor,
               GENESIS_SHINOBI_EXPERT_CONTROLS=a.profile, SDL_AUDIODRIVER='dummy',
               LNG_TEST_HIDDEN='1', LNG_SCRIPT='1')
    command = [str(package / a.exe.name), str(a.rom), '--no-launcher',
               '--input-script', str(script), '--benchmark', str(a.last+3),
               '--fresh-evidence', '--port', '4382']
    settings = dict(command=command, floor=a.floor, profile=a.profile,
                    interpreter=a.interpreter, exe_sha256=hashlib.sha256(a.exe.read_bytes()).hexdigest(),
                    rom_sha1=hashlib.sha1(a.rom.read_bytes()).hexdigest())
    (a.output / 'command.json').write_text(json.dumps(settings, indent=2)+'\n')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    with (a.output / 'run.log').open('w') as log:
        proc = subprocess.Popen(command, cwd=package, env=env, stdout=log,
                                stderr=subprocess.STDOUT, startupinfo=startup,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            code = proc.wait(timeout=a.timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
            code = 'timeout'
    log = (a.output / 'run.log').read_text(errors='replace')
    requests = {int(f): int(real) for real, f in re.findall(
        r'DUMP_RAM requested at frame (\d+) \(path=.*?ram-(\d+)\.ram\)', log)}
    rows = []
    for path in sorted(a.output.glob('ram-*.ram')):
        b = path.read_bytes()
        if len(b) != 65536:
            continue
        w = lambda off: int.from_bytes(b[off:off+2], 'big')
        d = lambda off: int.from_bytes(b[off:off+4], 'big')
        s = lambda v: v-65536 if v >= 32768 else v
        o = 0x412e
        frame = int(path.stem.split('-')[1])
        rows.append(dict(frame=frame, actual_frame=requests.get(frame),
                         flags=f'{w(o):04X}', handler=f'{d(o+6):06X}',
                         x=w(o+0x20), y=w(o+0x24),
                         vx=d(o+0x18), vy=d(o+0x1c),
                         ax=s(w(o+0x14)), ay=s(w(o+0x16)),
                         action=f'{w(o+0x2c):04X}', movement=f'{w(o+0x2a):04X}',
                         callback=f'{d(0x2a):06X}', input=f'{w(0xa):04X}',
                         round=b[0x37a6]+1, stage=b[0x37a8]+1,
                         free=w(0x5eba), ammo=b[0x37e3]))
    if rows:
        with (a.output / 'player.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    falls = []
    last_bad = False
    for row in rows:
        bad = row['flags'] == '80C0' or row['action'] == '002B'
        if bad and not last_bad:
            falls.append(row)
        last_bad = bad
    misses = [{'pc': pc, 'frame': int(frame)} for pc, frame in re.findall(
        r'(?:interior-label miss|computed dispatch miss|dispatch miss).*?\$([0-9A-Fa-f]{6}).*?frame[= ](\d+)', log)]
    summary = dict(settings, exit_code=code, sample_count=len(rows),
                   frame_mismatches=[r for r in rows if r['actual_frame'] != r['frame']],
                   falls=falls, misses=misses,
                   session_end=[l for l in log.splitlines() if '[session] loop ended:' in l],
                   fatal=[l for l in log.splitlines() if any(t in l for t in ('[ILLEGAL]', '[TRAP', 'runaway', '[FORCE_INTERP] HALT'))])
    if not rows:
        summary['invalid'] = 'No RAM samples were captured; this run is not evidence.'
    else:
        summary['invalid'] = None
    (a.output / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({k: summary[k] for k in ('exit_code','sample_count','falls','misses','session_end','fatal')}, separators=(',',':')))


if __name__ == '__main__':
    main()
