#!/usr/bin/env python3
"""Run every check in this directory. Exit non-zero if any of them fail."""

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
failed = []

for script in sorted(HERE.glob("test_*.py")):
    print(f"=== {script.name}")
    if subprocess.run([sys.executable, str(script)]).returncode:
        failed.append(script.name)
    print()

if failed:
    print(f"FAILED: {', '.join(failed)}")
    raise SystemExit(1)
print("everything passed")
