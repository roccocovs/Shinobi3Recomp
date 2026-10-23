import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run_capture(harness: Path, enabled: bool):
    env = os.environ.copy()
    env["GENESIS_R3_DIAG"] = "1" if enabled else "0"
    with tempfile.TemporaryDirectory(prefix="r3-diag-test-") as work:
        result = subprocess.run(
            [str(harness)], cwd=work, env=env, capture_output=True, text=True
        )
        if result.returncode:
            raise AssertionError(
                f"harness exited {result.returncode}:\n{result.stdout}\n{result.stderr}"
            )
        captures = list(Path(work).glob("R3-graphics-trace-*.jsonl"))
        if not enabled:
            assert not captures, "disabled diagnostics wrote a capture"
            return None, result.stderr
        assert len(captures) == 1, f"expected one capture, found {len(captures)}"
        rows = [json.loads(line) for line in captures[0].read_text().splitlines()]
        return rows, result.stderr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", required=True, type=Path)
    args = parser.parse_args()

    rows, stderr = run_capture(args.harness.resolve(), True)
    run_capture(args.harness.resolve(), False)
    header = next(row for row in rows if row["kind"] == "header")
    summary = next(row for row in rows if row["kind"] == "summary")
    first_miss = next(row for row in rows if row["kind"] == "dispatch_first")
    first_image = next(
        row for row in rows if row["kind"] == "display_first_watched_dispatch"
    )
    shutdown = next(row for row in rows if row["kind"] == "display_shutdown")

    assert header["schema"] == 3
    assert header["display_image_bytes"] == 66384
    assert first_miss["arg0"] == "0000202C"
    assert first_miss["d0"] == "11223344", "first dispatch record was overwritten"
    assert first_image["seq"] < shutdown["seq"]
    assert first_image["vram_bytes"] == 65536
    assert len(first_image["vram_hex"]) == 131072
    assert first_image["vram_hex"][:2] == "11"
    assert first_image["cram_words_hex"][:4] == "0123"
    assert first_image["vsram_words_hex"][:4] == "0042"
    assert first_image["sat_staging_hex"][:2] == "7B"
    assert shutdown["vram_hex"][:2] == "EE"
    assert shutdown["cram_words_hex"][:4] == "0789"
    assert shutdown["vsram_words_hex"][:4] == "4321"
    assert shutdown["sat_staging_hex"][:2] == "A4"
    assert summary["events_retained_in_capture_buffer"] == 512
    assert summary["events_total_in_capture_buffer"] == 702
    assert summary["events_dropped"] == 190
    assert summary["dispatch_stage2_total"] == 701
    assert summary["display_first_dispatch_retained"] == 1
    assert summary["display_shutdown_retained"] == 1
    assert "wrote R3-graphics-trace-" in stderr
    print(
        "R3 graphics capture regression passed: opt-in gating, first-miss context, "
        "raw first/shutdown display images, and bounded-ring overflow accounting."
    )


if __name__ == "__main__":
    main()
