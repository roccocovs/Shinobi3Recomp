#!/usr/bin/env python3
"""Check that the isolated recorder hooks follow generated ROM paths."""
import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated-dir", required=True, type=Path)
    args = ap.parse_args()
    sources = sorted(args.generated_dir.glob("shinobi3_part*.c"))
    dispatch = args.generated_dir / "shinobi3_dispatch.c"
    if dispatch.exists():
        sources.append(dispatch)
    if not sources:
        raise SystemExit("FAIL: generated C sources not found")
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in sources)
    for address in ("02EE38", "02EF28", "02EF36"):
        marker = f"/* ${address} */"
        if marker not in text:
            raise SystemExit(f"FAIL: generated instruction ${address} missing")
        pos = text.find(marker)
        window = text[pos:pos + 360]
        if "r4_scroll_trace_instruction" not in window:
            raise SystemExit(f"FAIL: no runtime hook at ${address}")
    if "r4_scroll_trace_continuation(addr, g_r4_scroll_trace_current_pc)" not in text:
        raise SystemExit("FAIL: dynamic continuation target is not instrumented")
    if "g_r4_scroll_trace_current_pc = 0x0023D0u" not in text:
        raise SystemExit("FAIL: stage-default writer PC is not retained")
    if "m68k_write16((uint32_t)(int32_t)(int16_t)0xF480" not in text:
        raise SystemExit("FAIL: generated $FFF480 write path is absent")
    print("PASS: updater, calculation, continuation, and stage-write hooks are generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
