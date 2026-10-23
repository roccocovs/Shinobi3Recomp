import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess

PLAYER_RAM_OFFSET = 0x412E
FIRST_FRAME = 4700
LAST_FRAME = 5200

def create_input_script(run_dir, max_frames):
    lines = [
        "WAIT 59",
        f"SCREENSHOT {run_dir / 'frame-00060.png'}",
        "WAIT 4640",
    ]
    for frame in range(FIRST_FRAME, LAST_FRAME + 1):
        if frame != FIRST_FRAME:
            lines.append("WAIT 1")
        lines.append(f"DUMP_RAM {run_dir / f'ram-{frame}.ram'}")
        if frame in (FIRST_FRAME, 4860, LAST_FRAME):
            lines.append(f"SCREENSHOT {run_dir / f'frame-{frame}.png'}")

    frame = LAST_FRAME
    while frame + 600 < max_frames:
        frame += 600
        lines.extend(("WAIT 600", f"SCREENSHOT {run_dir / f'frame-{frame}.png'}"))

    script = run_dir / "cold-demo.input"
    script.write_text("\n".join(lines) + "\n", encoding="ascii")
    return script

def run_floor(exe, rom, root, floor, max_frames, timeout):
    run_dir = root / f"floor-{floor}"
    if run_dir.exists():
        raise RuntimeError(f"refusing to overwrite {run_dir}")
    run_dir.mkdir(parents=True)
    package = run_dir / "package"
    package.mkdir()
    for name in ("Shinobi3Recomp.exe", "SDL2.dll", "debug.ini"):
        shutil.copy2(exe.parent / name, package / name)

    local_exe = package / exe.name
    script = create_input_script(run_dir, max_frames)
    env = os.environ.copy()
    env.update({
        "GENESIS_FORCE_INTERP": "0",
        "GENESIS_FLOOR": str(floor),
        "GENESIS_SHINOBI_EXPERT_CONTROLS": "1",
        "SDL_AUDIODRIVER": "dummy",
        "LNG_TEST_HIDDEN": "1",
        "LNG_SCRIPT": "1",
    })
    command = [
        str(local_exe), str(rom), "--no-launcher",
        "--input-script", str(script), "--max-frames", str(max_frames),
        "--target-fps", "240", "--fresh-evidence", "--port", "4382",
    ]
    (run_dir / "command.json").write_text(json.dumps({
        "floor": floor,
        "command": command,
        "exe_sha256": hashlib.sha256(local_exe.read_bytes()).hexdigest().upper(),
        "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest().upper(),
        "rom_in_package": (package / rom.name).exists(),
        "max_frames": max_frames,
    }, indent=2) + "\n", encoding="utf-8")

    with (run_dir / "stdout.log").open("w", encoding="utf-8") as stdout, \
         (run_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
        result = subprocess.run(
            command, cwd=package, env=env, stdout=stdout, stderr=stderr,
            timeout=timeout, check=False,
        )
    log = (run_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")
    requests = {}
    for line in log.splitlines():
        m = re.search(r"DUMP_RAM requested at frame (\d+) \(path=.*?ram-(\d+)\.ram\)", line)
        if m:
            requests[int(m.group(2))] = int(m.group(1))

    missing = []
    bad_states = []
    rows = {}
    for frame in range(FIRST_FRAME, LAST_FRAME + 1):
        dump = run_dir / f"ram-{frame}.ram"
        if not dump.is_file() or dump.stat().st_size != 65536:
            missing.append(frame)
            continue
        raw = dump.read_bytes()
        o = PLAYER_RAM_OFFSET
        flags = int.from_bytes(raw[o:o+2], "big")
        y = int.from_bytes(raw[o+0x24:o+0x26], "big")
        action = int.from_bytes(raw[o+0x2C:o+0x2E], "big")
        rows[frame] = {"flags": f"{flags:04X}", "action": f"{action:04X}", "y": f"{y:04X}"}
        if flags == 0x80C0 or action == 0x002B:
            bad_states.append({"frame": frame, **rows[frame]})

    shot = run_dir / "frame-4860.png"
    shot_hash = hashlib.sha256(shot.read_bytes()).hexdigest().upper() if shot.is_file() else None
    ended = next((line for line in reversed(log.splitlines()) if "[session] loop ended:" in line), None)
    return {
        "floor": floor,
        "exit_code": result.returncode,
        "session_end": ended,
        "frame_4860": rows.get(4860),
        "bad_state_count_4700_5200": len(bad_states),
        "first_bad_state": bad_states[0] if bad_states else None,
        "missing_or_invalid_dumps": missing,
        "dump_request_frame_mismatches": [
            {"file_frame": f, "requested_frame": req}
            for f, req in requests.items() if f != req
        ],
        "screenshot_4860_sha256": shot_hash,
        "exe_sha256": hashlib.sha256(local_exe.read_bytes()).hexdigest().upper(),
        "rom_in_package": (package / rom.name).exists(),
    }

def main():
    parser = argparse.ArgumentParser(description="Cold-boot Round 4 attract-demo regression check.")
    parser.add_argument("--exe", required=True, type=pathlib.Path)
    parser.add_argument("--rom", required=True, type=pathlib.Path)
    parser.add_argument("--results", required=True, type=pathlib.Path)
    parser.add_argument("--max-frames", type=int, default=5203)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    exe = args.exe.resolve()
    rom = args.rom.resolve()
    root = args.results.resolve()
    if not exe.is_file() or not rom.is_file():
        raise SystemExit("exe or ROM path does not exist")
    if root.exists():
        raise SystemExit(f"refusing to overwrite {root}")
    root.mkdir(parents=True)
    runs = [run_floor(exe, rom, root, floor, args.max_frames, args.timeout) for floor in (0, 1)]
    same_screenshot = runs[0]["screenshot_4860_sha256"] == runs[1]["screenshot_4860_sha256"]
    for run in runs:
        run["passed"] = (
            run["exit_code"] == 0
            and (run["frame_4860"] is not None and run["frame_4860"]["flags"] == "8000" and run["frame_4860"]["action"] == "0038")
            and run["bad_state_count_4700_5200"] == 0
            and not run["missing_or_invalid_dumps"]
            and not run["dump_request_frame_mismatches"]
            and run["rom_in_package"] is False
        )
    passed = all(r["passed"] for r in runs) and same_screenshot
    report = {"passed": passed, "matching_frame_4860_screenshot": same_screenshot, "runs": runs}
    (root / "regression-summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":")))
    raise SystemExit(0 if passed else 2)

if __name__ == "__main__":
    main()


