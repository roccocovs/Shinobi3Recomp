#!/usr/bin/env python3
"""Check the ROM sound handshake and the native scheduler's released-bus edge.

This is static/offline: it neither starts Shinobi nor runs a Z80 emulator.
"""
import argparse
import hashlib
import re
from pathlib import Path


ROM_SHA256 = "E0C50ED80FA1B75325344C2260A26841936D077E2AE1689C2522E3CC484739E3"


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def body(source, name):
    match = re.search(r"(?m)^(?:uint8_t|void)\s+" + re.escape(name) + r"\(", source)
    require(match is not None, f"missing {name}")
    end = source.index("\n}\n", match.start())
    return source[match.start():end + 3]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--generated", type=Path, required=True)
    p.add_argument("--glue", type=Path, required=True)
    a = p.parse_args()

    rom = a.rom.read_bytes()
    require(hashlib.sha256(rom).hexdigest().upper() == ROM_SHA256, "wrong ROM")
    # $06A444 calls the handshake with the return chain seen in the live trace.
    # Request bus -> wait for grant -> read Z80 mailbox busy bit -> release ->
    # five NOPs -> retry while busy. No WaitForVBlank or other yield lies in
    # the released-bus interval of this original 68000 routine.
    # The validated ROM digest identifies this routine. Checks below verify
    # generated bus-request, mailbox retry and scheduler-release behavior.

    generated = a.generated.read_text()
    routine = body(generated, "func_06A4A6")
    require("m68k_write16(0x00A11100u, (uint16_t)(0x0100u))" in routine,
            "native sound routine does not request the Z80 bus")
    require("m68k_read8(0x00A11100)" in routine and
            "m68k_read8(0x00A01FFD)" in routine and
            "m68k_write16(0x00A11100u, (uint16_t)(0x0000u))" in routine and
            "goto label_06A4A6;" in routine,
            "native sound routine differs from ROM busy/retry sequence")

    glue = a.glue.read_text()
    read = body(glue, "m68k_read8")
    write = body(glue, "m68k_write16")
    require("byte_addr == 0xA01FFDu" in read and
            "s_z80_mailbox_busy_seen = g_machine.bus.z80_busreq && (result & 0x80u)" in read,
            "native reader must retain the actual busy result while BUSREQ is held")
    released = write.index("gbus_write16(&g_machine.bus, byte_addr, val);")
    yielded = write.index("yield_to_main(GLUE_YIELD_Z80POLL);", released)
    require("z80_bus_release && s_interleave_active && !s_in_vblank_service" in
            write[released:yielded],
            "Z80 must run after the busy mailbox releases BUSREQ, before retry")
    require("s_z80_mailbox_busy_seen = 0" in write[released:yielded] and
            "s.z80_mailbox_busy_seen = s_z80_mailbox_busy_seen" in glue and
            "s_z80_mailbox_busy_seen     = s.z80_mailbox_busy_seen" in glue,
            "busy edge must clear after use and survive rollback")

    # Minimal scheduler model of the observed ROM loop. Before this edge was
    # added, all existing poll yields happened with BUSREQ asserted, so the
    # Z80 could never clear bit 7; repeating the loop did not change state.
    def attempts(release_yield):
        busy = True
        for attempt in range(1, 5):
            bus_requested = True
            if not busy:
                return attempt
            bus_requested = False
            if release_yield and not bus_requested:
                busy = False  # Z80 consumes its pending mailbox command.
        return None

    require(attempts(False) is None and attempts(True) == 2,
            "released-bus scheduling counterexample changed")
    print("PASS: ROM ${:06X} mailbox retry gives Z80 a scheduler turn only after BUSREQ release".format(0x06A4A6))


if __name__ == "__main__":
    main()
