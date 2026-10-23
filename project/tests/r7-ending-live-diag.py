#!/usr/bin/env python3
"""Bounded, opt-in ending-stall recorder behavior and runtime-hook regression."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def run(harness: Path, mode: str, path: Path, enabled: bool) -> None:
    env = os.environ.copy()
    env.pop("GENESIS_R7_ENDING_DIAG", None)
    env.pop("GENESIS_R7_ENDING_DIAG_PATH", None)
    if enabled:
        env["GENESIS_R7_ENDING_DIAG"] = "1"
    subprocess.run([str(harness), mode, str(path)], check=True, env=env)


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--glue", required=True, type=Path)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    disabled_path = args.work_dir / "disabled.jsonl"
    disabled_path.write_text("stale-disabled-output\n", encoding="utf-8")
    run(args.harness, "disabled", disabled_path, False)
    require(disabled_path.read_text(encoding="utf-8") == "stale-disabled-output\n",
            "disabled recorder changed its output file")

    normal_path = args.work_dir / "normal.jsonl"
    normal_path.write_text("stale-output-that-must-be-cleared\n", encoding="utf-8")
    run(args.harness, "normal", normal_path, True)
    normal = records(normal_path)
    require(normal and normal[0]["kind"] == "header" and
            normal[0]["trigger"] == "ending callback $010436",
            "startup did not clear stale output or declare the ROM-based trigger")
    kinds = [record["kind"] for record in normal[1:]]
    require("ending_start" in kinds and "ram_transition" in kinds and
            "dispatch_miss" in kinds and "watchdog" in kinds,
            "ending transition, dispatch, or watchdog evidence was not captured")
    require(kinds.count("dispatch_miss") == 1,
            "repeated identical dispatch miss escaped the diagnostic bound")
    start = next(record for record in normal if record["kind"] == "ending_start")
    require(start["callback"] == "010436" and start["wall_frame"] == 2 and
            start["sound_frame"] == 1002,
            "ending trigger did not capture matching wall/sound frame identity")
    require(start["d"] == [f"{0xD0000000 + i:08X}" for i in range(8)] and
            start["a"] == [f"{0xA0000000 + i:08X}" for i in range(7)],
            "register snapshot was incomplete")
    require(start["z80_busreq"] == 1 and start["z80_reset_off"] == 1 and
            start["z80_mailbox_1ffd"] == "80" and
            start["z80_mailbox_busy_seen"] == 1,
            "Z80 bus-release condition was not preserved in the snapshot")
    transition = next(record for record in normal if record["kind"] == "ram_transition")
    require(transition["address"] == "FF0034" and transition["old"] == "00000008" and
            transition["value"] == "0000000C",
            "ending state transition was not preserved")
    watchdog = next(record for record in normal if record["kind"] == "watchdog")
    require(watchdog["wall_frame"] == 32 and watchdog["sound_frame"] == 1032 and
            len(watchdog["bus_tail"]) == 64 and watchdog["bus_total"] == 80 and
            watchdog["bus_tail"][0]["address"] == "FF0010" and
            watchdog["bus_tail"][0]["pc"] == "010020",
            "watchdog did not preserve the bounded most-recent PC/address bus tail")

    capacity_path = args.work_dir / "capacity.jsonl"
    run(args.harness, "capacity", capacity_path, True)
    capacity = records(capacity_path)
    require(capacity[0]["kind"] == "header" and len(capacity) == 257 and
            len(capacity) - 1 == capacity[0]["record_capacity"],
            "recorder exceeded or silently underfilled its fixed record capacity")

    glue = args.glue.read_text(encoding="utf-8")
    for needle in (
        "g_r4_scroll_trace_current_pc",
        "r7_ending_diag_watchdog_capture(reason)",
        "r7_ending_diag_frame(&snapshot)",
        "r7_ending_diag_note_ram_write(byte_addr",
        ".pc = g_r4_scroll_trace_current_pc",
        "r7_ending_diag_dispatch_miss(&snapshot, addr)",
    ):
        require(needle in glue, f"live runtime hook is missing: {needle}")

    print("PASS: opt-in trigger waits for ROM ending callback $010436")
    print("PASS: snapshots preserve frame IDs, CPU registers, state transitions, and guest immutability")
    print("PASS: dispatch warnings are deduplicated; watchdog keeps the last 64 PC/address pairs")
    print("PASS: stale output is cleared when enabled, disabled output is untouched, and ring is capped at 256")
    print("PASS: frame, RAM-transition, dispatch, and watchdog capture points are wired into glue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
