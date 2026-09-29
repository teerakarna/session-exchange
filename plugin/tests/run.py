#!/usr/bin/env python3
"""Run every check in this directory, or only the files named. Exit non-zero if any of them fail.

The argument is for the mutation sweep (#43), which runs this once per mutation to learn whether one
named file objected. It ran all fourteen to find out about one, and `test_cli.py` alone is two
thirds of the suite while being the `caught_by` of twelve mutations out of 244, so the other 232
were paying for it. Taking a selection here rather than having the sweep invoke a test file directly
keeps the `=== <file>` headers and the `FAILED:` line that all of the sweep's scoring reads: the
output of a one-file run is the shape of a full one, so nothing downstream knows the difference.

An unknown name is a refusal rather than an empty run. A run of nothing exits 0, which the sweep
reads as "the suite passed, so nothing asserts this rule", so a typo would report a whole table as
unasserted and look exactly like a finding.
"""

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
scripts = sorted(HERE.glob("test_*.py"))

if sys.argv[1:]:
    known = {script.name: script for script in scripts}
    unknown = [name for name in sys.argv[1:] if name not in known]
    if unknown:
        raise SystemExit(f"no test file called {', '.join(unknown)} in {HERE}")
    # `dict.fromkeys` keeps the order given and drops a repeat, which is not tidiness: a name twice
    # runs the file twice and lands in the `FAILED:` line twice, and `catchers` hands the sweep a
    # list with a duplicate in it.
    scripts = [known[name] for name in dict.fromkeys(sys.argv[1:])]

failed = []

# `flush` because the child writes to this same fd directly. Without it, stdout is block-buffered
# the moment it is a pipe rather than a terminal - which is every CI log and every capture the
# mutation sweep takes - so all of these headers sit in the buffer until exit and arrive after all
# of the output they are meant to be labelling. On a terminal it looked right.
for script in scripts:
    print(f"=== {script.name}", flush=True)
    if subprocess.run([sys.executable, str(script)]).returncode:
        failed.append(script.name)
    print(flush=True)

if failed:
    print(f"FAILED: {', '.join(failed)}")
    raise SystemExit(1)
print("everything passed")
