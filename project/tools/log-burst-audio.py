#!/usr/bin/env python3
"""Sample the Shinobi trace command server once per second while the game runs."""
import argparse, csv, datetime, json, os, socket, sys, time
from collections import deque

class Client:
    def __init__(self, host, port, timeout=3.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.file = self.sock.makefile('rwb', buffering=0)
        self.seq = 0
    def ask(self, cmd, **kwargs):
        self.seq += 1
        data = {'id': self.seq, 'cmd': cmd, **kwargs}
        self.file.write((json.dumps(data, separators=(',', ':')) + '\n').encode())
        line = self.file.readline()
        if not line:
            raise ConnectionError('server closed connection')
        obj = json.loads(line.decode('utf-8', errors='replace'))
        if not obj.get('ok', False):
            raise RuntimeError(f'{cmd}: {obj}')
        return obj
    def close(self):
        try: self.file.close()
        finally: self.sock.close()

def word(client, addr):
    return int(client.ask('read_ram', addr=addr, size=2)['hex'], 16)

def write_snapshot_ring(path, snapshots):
    """Atomically retain only the newest sound-block snapshots."""
    tmp_path = f'{path}.{os.getpid()}.{time.time_ns()}.tmp'
    with open(tmp_path, 'x', encoding='utf-8', newline='\n') as f:
        for snapshot in snapshots:
            f.write(json.dumps(snapshot, separators=(',', ':')) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)

def enter_pressed():
    """Poll Enter without blocking the one-second sampling loop (Windows console)."""
    if os.name != 'nt' or not sys.stdin.isatty():
        return False
    try:
        import msvcrt
        pressed = False
        while msvcrt.kbhit():
            key = msvcrt.getwch()
            if key in ('\x00', '\xe0'):
                if msvcrt.kbhit(): msvcrt.getwch()
            elif key in ('\r', '\n'):
                pressed = True
        return pressed
    except (ImportError, OSError):
        return False

def capture_event(client, writer, csv_file, event_dir, last_guest_frame):
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y%m%dT%H%M%S%fZ')
    prefix = os.path.join(event_dir, f'event-{stamp}-').replace('\\', '/')
    try:
        guest_frame = int(client.ask('frame_info')['current_frame'])
    except (OSError, EOFError, ConnectionError, RuntimeError, ValueError, KeyError,
            json.JSONDecodeError):
        guest_frame = last_guest_frame
    timestamp = now.isoformat(timespec='milliseconds')
    writer.writerow({'record_type': 'EVENT', 'timestamp_utc': timestamp,
                     'guest_frame': guest_frame, 'event': 'manual_sound_glitch',
                     'event_prefix': prefix})
    csv_file.flush()
    try:
        result = client.ask('snd_dump', prefix=prefix)
        result_path = prefix + 'result.json'
        with open(result_path, 'x', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f'[event] frame={guest_frame} dump={prefix} (chip_ring.txt, snd_ring.txt, z80_ram.bin)', flush=True)
    except (OSError, EOFError, ConnectionError, RuntimeError, ValueError, KeyError,
            json.JSONDecodeError) as exc:
        writer.writerow({'record_type': 'EVENT_ERROR', 'timestamp_utc': timestamp,
                         'guest_frame': guest_frame, 'event': repr(exc),
                         'event_prefix': prefix})
        csv_file.flush()
        print(f'[event] frame={guest_frame} dump failed: {exc}', file=sys.stderr, flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
    ap.add_argument('--port', type=int, default=4382)
    ap.add_argument('--interval', type=float, default=1.0)
    ap.add_argument('--output', required=True)
    ap.add_argument('--sound-snapshots', help='sidecar JSONL ring path; defaults to a unique file beside --output')
    ap.add_argument('--event-dir', help='directory for timestamped snd_dump files; defaults beside --output')
    ap.add_argument('--stop-file', help='stop after the current sample when this file appears')
    ap.add_argument('--stop-wav-on-exit', action='store_true', help='finalize an active audio_wav recording on exit')
    ap.add_argument('--probe-only', action='store_true', help='check the four command-server queries and exit')
    args = ap.parse_args()
    client = None
    last_error = None
    for _ in range(120):
        try:
            client = Client(args.host, args.port)
            break
        except OSError as exc:
            last_error = repr(exc)
            time.sleep(.25)
    if client is None:
        raise SystemExit(f'No Shinobi command server at {args.host}:{args.port}; last error: {last_error}')
    try:
        probe = {}
        for name, call in (
            ('ping', lambda: client.ask('ping')),
            ('read_ram', lambda: client.ask('read_ram', addr='FF5EBA', size=2)),
            ('audio_stats', lambda: client.ask('audio_stats')),
            ('frame_performance', lambda: client.ask('frame_performance')),
        ):
            try:
                probe[name] = {'ok': True, 'keys': sorted(call().keys())}
            except (OSError, EOFError, ConnectionError, RuntimeError, ValueError, KeyError,
                    json.JSONDecodeError) as exc:
                probe[name] = {'ok': False, 'error': repr(exc)}
        with open(args.output + '.probe.json', 'w', encoding='utf-8') as f:
            json.dump(probe, f, indent=2)
        print('Probe results: ' + ', '.join(f'{k}={"reply" if v["ok"] else "no reply"}' for k, v in probe.items()), flush=True)
        if args.probe_only:
            return
        if not all(v['ok'] for v in probe.values()):
            raise SystemExit(f'One or more command probes failed; details saved to {args.output}.probe.json')
        free = word(client, 'FF5EBA')
        ammo = word(client, 'FF37E2')
        aud = client.ask('audio_stats')
        perf = client.ask('frame_performance')
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        sound_snapshot_path = args.sound_snapshots or f'{args.output}.sound-block-{stamp}.jsonl'
        event_dir = os.path.abspath(args.event_dir or os.path.dirname(os.path.abspath(args.output)))
        os.makedirs(event_dir, exist_ok=True)
        if os.path.exists(sound_snapshot_path):
            raise SystemExit(f'Sound snapshot file already exists; choose a new path: {sound_snapshot_path}')
        fields = ['record_type','timestamp_utc','guest_frame','event','event_prefix','free_count','shuriken_count','underrun_flushes','dropped_flushes','worst_frame','worst_phase_sum_us']
        print(f"Connected to 127.0.0.1:{args.port}; read-only logger active; CSV={args.output}; sound snapshots={sound_snapshot_path}", flush=True)
        if os.name == 'nt' and sys.stdin.isatty():
            print('Press Enter immediately after a sound glitch to log an EVENT row and dump sound rings; Ctrl+C stops capture and finalizes WAV.', flush=True)
        failures = 0
        started_at = time.monotonic()
        next_heartbeat = started_at + 10.0
        sample_count = 0
        last_guest_frame = 0
        sound_snapshots = deque(maxlen=30)
        with open(args.output, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); f.flush()
            next_at = time.monotonic()
            while not (args.stop_file and os.path.exists(args.stop_file)):
                next_at += args.interval
                try:
                    a = client.ask('audio_stats')
                    guest_frame = int(client.ask('frame_info')['current_frame'])
                    fr = client.ask('frame_performance')
                    ram = client.ask('read_ram', addr='FFF800', size=0x400)
                    ram_hex = ram.get('hex', '')
                    if len(ram_hex) != 0x800:
                        raise ValueError(f"sound RAM snapshot returned {len(ram_hex) // 2} bytes, expected 1024")
                    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
                    sound_snapshots.append({'timestamp_utc': timestamp, 'guest_frame': guest_frame,
                                            'start': 'FFF800',
                                            'end': 'FFFBFF', 'size_bytes': 0x400, 'hex': ram_hex})
                    write_snapshot_ring(sound_snapshot_path, sound_snapshots)
                    rows = fr.get('rows', [])
                    slow = max(((sum(map(int, row[1:])), int(row[0])) for row in rows), default=(0,0))
                    w.writerow({'record_type':'SAMPLE','timestamp_utc':timestamp, 'guest_frame':guest_frame,
                                'free_count':word(client,'FF5EBA'), 'shuriken_count':word(client,'FF37E2'),
                                'underrun_flushes':a.get('underrun_flushes',''), 'dropped_flushes':a.get('dropped_flushes',''),
                                'worst_frame':slow[1], 'worst_phase_sum_us':slow[0]})
                    f.flush(); failures = 0; sample_count += 1; last_guest_frame = guest_frame
                except (OSError, EOFError, ConnectionError, RuntimeError, ValueError, KeyError, json.JSONDecodeError):
                    failures += 1
                    if failures >= 3: break
                now = time.monotonic()
                if now >= next_heartbeat:
                    print(f"[heartbeat] elapsed={int(now-started_at)}s samples={sample_count} sound_snapshots={len(sound_snapshots)}", flush=True)
                    next_heartbeat = now + 10.0
                if enter_pressed():
                    capture_event(client, w, f, event_dir, last_guest_frame)
                remaining = max(0, next_at-time.monotonic())
                while remaining > 0:
                    time.sleep(min(.05, remaining))
                    if enter_pressed():
                        capture_event(client, w, f, event_dir, last_guest_frame)
                    remaining = max(0, next_at-time.monotonic())
    except KeyboardInterrupt:
        print('[logger] stopped by Ctrl+C', flush=True)
    finally:
        if args.stop_wav_on_exit:
            try:
                client.ask('audio_wav', action='stop')
                print('[wav] recording finalized', flush=True)
            except (OSError, EOFError, ConnectionError, RuntimeError, ValueError, KeyError,
                    json.JSONDecodeError) as exc:
                print(f'[wav] finalization failed: {exc}', file=sys.stderr, flush=True)
        client.close()

if __name__ == '__main__': main()


