#!/usr/bin/env python3
"""Read-only summary of a runner chip_ring.txt dump.

The runner stamps events with guest wall frame (wf), scanline (sl), and
register-port writes. Time is estimated from the NTSC frame rate and 262 lines.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


LINE_RE = re.compile(
    r"f=(?P<vint>\d+)\s+sl=(?P<line>\d+)\s+"
    r"(?:(?:FM\s+p(?P<port>\d+))|(?P<psg>PSG))\s+"
    r"\$(?P<value>[0-9A-Fa-f]{2})(?:.*?\bwf=(?P<wall>\d+))?"
)
LINES_PER_FRAME = 262


@dataclass
class Event:
    kind: str
    port: int | None
    value: int
    frame: int
    line: int


@dataclass
class Lane:
    name: str
    last_write: float | None = None
    last_write_at: tuple[int, int] | None = None
    last_write_reg: str = ""
    last_key_on: float | None = None
    last_key_on_at: tuple[int, int] | None = None
    active: bool | None = None
    was_active: bool = False

    def wrote(self, t: float, at: tuple[int, int], reg: str) -> None:
        self.last_write = t
        self.last_write_at = at
        self.last_write_reg = reg

    def turned_on(self, t: float, at: tuple[int, int]) -> None:
        self.active = True
        self.was_active = True
        self.last_key_on = t
        self.last_key_on_at = at


def parse_events(path: Path) -> list[Event]:
    events: list[Event] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            match = LINE_RE.search(line)
            if not match:
                continue
            frame = int(match.group("wall") or match.group("vint"))
            events.append(Event(
                kind="PSG" if match.group("psg") else "FM",
                port=int(match.group("port")) if match.group("port") else None,
                value=int(match.group("value"), 16),
                frame=frame,
                line=int(match.group("line")),
            ))
    return events


def fm_channel(register: int, bank: int) -> int | None:
    if 0x30 <= register <= 0x9F:
        channel = register & 3
        return channel + (3 if bank else 0) if channel < 3 else None
    if 0xA0 <= register <= 0xA2 or 0xB0 <= register <= 0xB2:
        return (register & 3) + (3 if bank else 0)
    if 0xA4 <= register <= 0xA6 or 0xB4 <= register <= 0xB6:
        return (register & 3) + (3 if bank else 0)
    # Channel-3 special frequency registers belong to FM3.
    if not bank and 0xA8 <= register <= 0xAE:
        return 2
    return None


def decode(events: list[Event], fps: float) -> tuple[dict[str, Lane], float, int]:
    lanes = {f"FM{i}": Lane(f"FM{i}") for i in range(1, 7)}
    lanes["DAC"] = Lane("DAC", active=False)
    for i in range(1, 4):
        lanes[f"PSG{i}"] = Lane(f"PSG{i}", active=None)
    lanes["Noise"] = Lane("Noise", active=None)

    address_latch: dict[int, int | None] = {0: None, 1: None}
    psg_latch: int | None = None
    psg_volume = [15, 15, 15, 15]
    dac_enabled = False
    end_tick = max((e.frame * LINES_PER_FRAME + e.line for e in events), default=0)

    for event in events:
        tick = event.frame * LINES_PER_FRAME + event.line
        when = tick / (fps * LINES_PER_FRAME)
        at = (event.frame, event.line)

        if event.kind == "FM":
            assert event.port is not None
            if event.port in (0, 2):
                address_latch[event.port // 2] = event.value
                continue

            bank = event.port // 2
            register = address_latch[bank]
            if register is None:
                continue
            value = event.value

            if bank == 0 and register == 0x28:
                channel_index = value & 3
                if channel_index == 3:
                    continue
                channel = channel_index + (3 if value & 4 else 0)
                lane = lanes[f"FM{channel + 1}"]
                lane.wrote(when, at, f"${register:02X}")
                if value & 0xF0:
                    lane.turned_on(when, at)
                else:
                    lane.active = False
            elif bank == 0 and register == 0x2B:
                lanes["DAC"].wrote(when, at, f"${register:02X}")
                new_enabled = bool(value & 0x80)
                if new_enabled and not dac_enabled:
                    lanes["DAC"].turned_on(when, at)
                lanes["DAC"].active = new_enabled
                dac_enabled = new_enabled
            elif bank == 0 and register == 0x2A:
                lanes["DAC"].wrote(when, at, f"${register:02X}")
                if dac_enabled:
                    lanes["DAC"].was_active = True
            else:
                channel = fm_channel(register, bank)
                if channel is not None:
                    lanes[f"FM{channel + 1}"].wrote(when, at, f"${register:02X}")
            continue

        value = event.value
        if value & 0x80:
            psg_latch = (value >> 4) & 7
            data = value & 0x0F
        elif psg_latch is not None:
            data = value & (0x3F if psg_latch in (0, 2, 4) else 0x0F)
        else:
            continue

        register = psg_latch
        if register in (0, 2, 4):
            lane = lanes[f"PSG{register // 2 + 1}"]
            lane.wrote(when, at, f"PSG tone{register // 2 + 1}")
        elif register in (1, 3, 5, 7):
            channel = (register - 1) // 2
            lane = lanes["Noise" if channel == 3 else f"PSG{channel + 1}"]
            lane.wrote(when, at, f"PSG volume{channel + 1}")
            was_muted = psg_volume[channel] >= 15
            psg_volume[channel] = data & 0x0F
            now_active = psg_volume[channel] < 15
            lane.active = now_active
            if now_active:
                lane.was_active = True
                if was_muted:
                    lane.turned_on(when, at)
        elif register == 6:
            lane = lanes["Noise"]
            lane.wrote(when, at, "PSG noise-control")
            if psg_volume[3] < 15:
                lane.was_active = True

    return lanes, end_tick / (fps * LINES_PER_FRAME), end_tick


def since_end(value: float | None, end: float) -> str:
    return "n/a" if value is None else f"{max(0.0, end - value):.2f}s ago"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="chip_ring.txt to read")
    parser.add_argument("--fps", type=float, default=59.94, help="guest frame rate (default 59.94)")
    parser.add_argument("--silence-after", type=float, default=2.0,
                        help="flag active lanes with no lane writes for this many seconds (default 2)")
    args = parser.parse_args()
    if args.fps <= 0 or args.silence_after < 0:
        parser.error("--fps must be positive and --silence-after cannot be negative")
    try:
        events = parse_events(args.dump)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not events:
        print("error: no recognized FM/PSG events; expected runner chip_ring.txt format", file=sys.stderr)
        return 2

    lanes, end, end_tick = decode(events, args.fps)
    first_tick = min(e.frame * LINES_PER_FRAME + e.line for e in events)
    coverage = (end_tick - first_tick) / (args.fps * LINES_PER_FRAME)
    print(f"Dump: {args.dump}")
    print(f"Parsed {len(events)} events; estimated coverage {coverage:.2f}s; end at guest frame {end_tick // LINES_PER_FRAME} line {end_tick % LINES_PER_FRAME}.")
    print("Lane   State    Last key-on          Last write           Gap    Flag")
    for lane in lanes.values():
        state = "ON" if lane.active is True else "OFF" if lane.active is False else "UNKNOWN"
        gap = None if lane.last_write is None else max(0.0, end - lane.last_write)
        flag = "ACTIVE_NO_WRITES" if lane.active is True and lane.was_active and gap is not None and gap >= args.silence_after else ""
        last_write = "n/a" if lane.last_write is None else f"{since_end(lane.last_write, end)} {lane.last_write_reg}"
        gap_text = f"{gap:.2f}s" if gap is not None else "n/a"
        print(f"{lane.name:<6} {state:<8} {since_end(lane.last_key_on, end):<14} {last_write:<21} {gap_text:>7} {flag}")
    print("Note: timestamps are approximated from wf/sl at the selected frame rate; PSG 'key-on' means volume changed from muted to audible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
