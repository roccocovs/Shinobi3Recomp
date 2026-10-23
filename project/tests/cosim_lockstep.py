#!/usr/bin/env python3
"""Compare a cold-boot native run with the clean-room interpreter.

The two game windows are hidden. Each run gets a separate working directory,
state files, and cosim port; both consume the same optional input script.
"""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


def hide_process_windows(pid: int) -> None:
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd: int, _param: int) -> bool:
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid and user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 0)  # SW_HIDE: keep automated checks off the desktop
        return True

    user32.EnumWindows(callback_type(visit), 0)


class Side:
    def __init__(self, label: str, exe: Path, rom: Path, port: int,
                 script: Path | None, interpreter: bool, work: Path,
                 clock: str, stride: int, waitvbl_pc: str | None):
        self.label = label
        self.port = port
        self.cwd = work / label
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.log = (self.cwd / f"{label}.log").open("w", encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "GENESIS_COSIM_PORT": str(port),
            "GENESIS_COSIM_STRIDE": str(stride),
            "GENESIS_COSIM_CLOCK": clock,
            "GENESIS_FORCE_INTERP": "1" if interpreter else "0",
            "GENESIS_FLOOR": "0",
            "GENESIS_SHINOBI_EXPERT_CONTROLS": "1",
            "SDL_AUDIODRIVER": "dummy",
        })
        if waitvbl_pc:
            env["GENESIS_COSIM_WAITVBL_PC"] = waitvbl_pc
        command = [str(exe), str(rom), "--no-launcher", "--turbo"]
        if script:
            command += ["--input-script", str(script)]
        startupinfo = None
        flags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            flags = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(
            command, cwd=self.cwd, env=env, stdout=self.log,
            stderr=subprocess.STDOUT, startupinfo=startupinfo,
            creationflags=flags)
        self.sock = self._connect()
        hide_process_windows(self.process.pid)
        self.buffer = b""

    def _connect(self) -> socket.socket:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.label} exited; inspect {self.cwd / (self.label + '.log')}")
            try:
                sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                sock.settimeout(30)
                return sock
            except OSError:
                time.sleep(0.1)
        raise TimeoutError(f"{self.label} did not open cosim port {self.port}")

    def line(self) -> str:
        while b"\n" not in self.buffer:
            data = self.sock.recv(4096)
            if not data:
                raise EOFError(f"{self.label} closed the cosim connection")
            self.buffer += data
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("ascii", errors="replace").strip()

    def command(self, value: str) -> str:
        self.sock.sendall((value + "\n").encode("ascii"))
        return self.line()

    def block(self, value: str) -> str:
        self.sock.sendall((value + "\n").encode("ascii"))
        lines = []
        while True:
            line = self.line()
            if line == "end":
                return "\n".join(lines)
            lines.append(line)

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.log.close()


def fields(response: str) -> dict[str, str]:
    tokens = response.split()
    # `step` replies start with a status word (`parked`) before the key/value
    # fields, unlike the `chain` and `cpu` replies. Drop only that status word
    # so the parser sees cp/cycle/chain instead of pairing shifted tokens.
    if tokens and tokens[0] == "parked":
        tokens = tokens[1:]
    if len(tokens) % 2:
        raise ValueError(f"malformed cosim response: {response!r}")
    return {tokens[i]: tokens[i + 1] for i in range(0, len(tokens) - 1, 2)}


def start_pair(exe: Path, rom: Path, script: Path | None, work: Path,
               clock: str, stride: int, waitvbl_pc: str | None,
               porta: int, portb: int, name: str) -> tuple[Side, Side]:
    native = Side(f"{name}-native", exe, rom, porta, script, False, work,
                  clock, stride, waitvbl_pc)
    try:
        interp = Side(f"{name}-interp", exe, rom, portb, script, True, work,
                      clock, stride, waitvbl_pc)
    except Exception:
        native.close()
        raise
    return native, interp


def compare_steps(native: Side, interp: Side, count: int) -> tuple[dict[str, str], dict[str, str]]:
    left = fields(native.command(f"step {count}"))
    right = fields(interp.command(f"step {count}"))
    required = {"cp", "chain"}
    if not required.issubset(left) or not required.issubset(right):
        raise RuntimeError(f"missing checkpoint fields: native={left} interp={right}")
    return left, right


def current_status(native: Side, interp: Side) -> tuple[dict[str, str], dict[str, str]]:
    left = fields(native.command("status"))
    right = fields(interp.command("status"))
    required = {"cp", "chain"}
    if not required.issubset(left) or not required.issubset(right):
        raise RuntimeError(f"missing initial status fields: native={left} interp={right}")
    return left, right


def checkpoints_match(left: dict[str, str], right: dict[str, str]) -> bool:
    return left["cp"] == right["cp"] and left["chain"] == right["chain"]


def print_checkpoint_details(native: Side, interp: Side, checkpoint: int) -> None:
    print(f"Checkpoint {checkpoint} state details:")
    for side in (native, interp):
        print(f"[{side.label}] cpu: {side.command('cpu')}")
        print(f"[{side.label}] sub: {side.command('sub')}")
        print(f"[{side.label}] timing: {side.command('timingfields')}")
        print(f"[{side.label}] vdp: {side.command('vdpfields')}")
        print(f"[{side.label}] recent PCs:\n" + "\n".join(
            side.block("window 12").splitlines()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--max-checkpoints", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=1,
                        help="check this many checkpoints per socket round-trip")
    parser.add_argument("--refine-batch-size", type=int, default=1,
                        help="socket batch size after --refine-after (default: one checkpoint)")
    parser.add_argument("--refine-after", type=int,
                        help="switch from the configured stride to one cycle after this checkpoint")
    parser.add_argument("--clock", choices=("frame", "insn"), default="frame")
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--porta", type=int, default=4720)
    parser.add_argument("--portb", type=int, default=4721)
    parser.add_argument("--waitvbl-pc", help="hex WaitForVBlank entry used by interpreter pacing")
    parser.add_argument("--work-dir", type=Path, help="retain per-side logs and files here")
    args = parser.parse_args()
    exe, rom = args.exe.resolve(), args.rom.resolve()
    script = args.script.resolve() if args.script else None
    if not exe.is_file() or not rom.is_file() or (script and not script.is_file()):
        parser.error("exe, ROM, and optional input script must exist")
    if (args.max_checkpoints < 1 or args.stride < 1 or args.batch_size < 1
            or args.refine_batch_size < 1
            or args.porta == args.portb):
        parser.error("checkpoint count, stride, and batch sizes must be positive; ports must differ")
    if args.refine_after is not None and (args.clock != "insn" or args.refine_after < 1):
        parser.error("--refine-after requires --clock insn and a positive checkpoint number")

    temporary = None
    if args.work_dir:
        work = args.work_dir.resolve()
        work.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="shinobi3-cosim-")
        work = Path(temporary.name)

    native = interp = None
    try:
        native, interp = start_pair(exe, rom, script, work, args.clock, args.stride,
                                    args.waitvbl_pc, args.porta, args.portb, "run")
        initial_native, initial_interp = current_status(native, interp)
        if not checkpoints_match(initial_native, initial_interp):
            print(f"FIRST DIVERGENCE before stepping: native={initial_native} interp={initial_interp}")
            print(f"Logs: {native.cwd} and {interp.cwd}")
            return 1
        initial_cp = int(initial_native["cp"])
        if args.refine_after is not None and not (
                initial_cp <= args.refine_after <= initial_cp + args.max_checkpoints):
            parser.error("--refine-after must fall within the requested checkpoint range")
        print(f"Cold boot: native vs interpreter; clock={args.clock}, stride={args.stride}")
        matched = 0
        refined = False
        while matched < args.max_checkpoints:
            current_cp = initial_cp + matched
            if args.refine_after == current_cp and not refined:
                if native.command("stride 1") != "ok" or interp.command("stride 1") != "ok":
                    raise RuntimeError("cosim server rejected one-cycle refinement")
                refined = True
                print(f"Refined checkpoint stride to 1 after checkpoint {current_cp}")
            count = min(args.batch_size, args.max_checkpoints - matched)
            if refined:
                count = min(count, args.refine_batch_size)
            if args.refine_after is not None and not refined:
                count = min(count, args.refine_after - current_cp)
            previous = matched
            left, right = compare_steps(native, interp, count)
            matched += count
            if not checkpoints_match(left, right):
                lo = initial_cp + previous
                hi = int(left["cp"])
                if count == 1:
                    print(f"FIRST DIVERGENCE checkpoint={hi}: native={left} interp={right}")
                else:
                    print(f"Mismatch lies within checkpoints {lo + 1}..{hi}; "
                          f"last sampled state: native={left} interp={right}")
                print_checkpoint_details(native, interp, hi)
                print(f"Logs: {native.cwd} and {interp.cwd}")
                return 1
            if matched % 100 == 0 or matched == args.max_checkpoints:
                print(f"matched {matched}/{args.max_checkpoints}; checkpoint={left['cp']}")
        print(f"PASS: {args.max_checkpoints} checkpoints matched")
        print(f"Logs: {native.cwd} and {interp.cwd}")
        return 0
    finally:
        if interp:
            interp.close()
        if native:
            native.close()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    sys.exit(main())
