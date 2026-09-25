#!/usr/bin/env python3
"""Run every check in this directory. Exit non-zero if any of them fail."""

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
failed = []

# `flush` because the child writes to this same fd directly. Without it, stdout is block-buffered
# the moment it is a pipe rather than a terminal - which is every CI log and every capture the
# mutation sweep takes - so all of these headers sit in the buffer until exit and arrive after all
# of the output they are meant to be labelling. On a terminal it looked right.
for script in sorted(HERE.glob("test_*.py")):
    print(f"=== {script.name}", flush=True)
    if subprocess.run([sys.executable, str(script)]).returncode:
        failed.append(script.name)
    print(flush=True)

if failed:
    print(f"FAILED: {', '.join(failed)}")
    raise SystemExit(1)
print("everything passed")
