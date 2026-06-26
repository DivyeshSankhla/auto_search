#!/usr/bin/env python3
"""
Run jobsearch_partX.py through jobsearch_partY.py with shared CLI args.

Each part's combined stdout/stderr is written to:
  job_search_N/last_run_output.txt
  job_search_general/last_run_output.txt   (with --general or --general-only)
(overwritten on every run)

Examples:
  python3 run_job_search_range.py 3 7 --days 15
  python3 run_job_search_range.py 1 10 --limit 50 --days 4 --general
  python3 run_job_search_range.py --general-only --sites remoteok,hn --days 7
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT_NAME = "last_run_output.txt"
MIN_PART = 1
MAX_PART = 10
GENERAL_DIR = ROOT / "job_search_general"
GENERAL_SCRIPT = GENERAL_DIR / "job_search_general.py"


def run_script(script: Path, out_path: Path, forward: list[str]) -> int:
    cmd = [sys.executable, str(script), *forward]
    print(f"Running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    header = f"# command: {' '.join(cmd)}\n# exit_code: {result.returncode}\n\n"
    out_path.write_text(header + result.stdout + result.stderr, encoding="utf-8")
    print(f"  -> wrote {out_path}", flush=True)
    return result.returncode


def parse_cli(argv: list[str] | None) -> tuple[int | None, int | None, bool, bool, list[str]]:
    """Parse wrapper args; everything else is forwarded to each job search script."""
    raw = list(argv if argv is not None else sys.argv[1:])
    start: int | None = None
    end: int | None = None
    if raw and raw[0].isdigit():
        start = int(raw.pop(0))
    if raw and raw[0].isdigit():
        end = int(raw.pop(0))

    general = False
    general_only = False
    forward: list[str] = []
    idx = 0
    while idx < len(raw):
        arg = raw[idx]
        if arg == "--general":
            general = True
            idx += 1
        elif arg == "--general-only":
            general_only = True
            idx += 1
        elif arg == "--":
            forward.extend(raw[idx + 1 :])
            break
        else:
            forward.append(arg)
            idx += 1
    return start, end, general, general_only, forward


def main(argv: list[str] | None = None) -> int:
    start, end, general, general_only, forward = parse_cli(argv)
    exit_code = 0

    if not general_only:
        if start is None or end is None:
            print("error: start and end are required unless --general-only is set", file=sys.stderr)
            return 2
        if start > end:
            print("error: start must be <= end", file=sys.stderr)
            return 2
        if start < MIN_PART or end > MAX_PART:
            print(f"error: part range must be {MIN_PART}–{MAX_PART}", file=sys.stderr)
            return 2

        for part in range(start, end + 1):
            part_dir = ROOT / f"job_search_{part}"
            script = part_dir / f"jobsearch_part{part}.py"
            out_path = part_dir / OUTPUT_NAME
            if not script.is_file():
                print(f"error: missing {script}", file=sys.stderr)
                exit_code = 1
                continue
            code = run_script(script, out_path, forward)
            if code != 0:
                exit_code = code

    if general or general_only:
        out_path = GENERAL_DIR / OUTPUT_NAME
        if not GENERAL_SCRIPT.is_file():
            print(f"error: missing {GENERAL_SCRIPT}", file=sys.stderr)
            return 1
        code = run_script(GENERAL_SCRIPT, out_path, forward)
        if code != 0:
            exit_code = code

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
