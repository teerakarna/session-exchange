#!/usr/bin/env python3
"""The regression the handoff parser never had.

Run it: `python3 plugin/tests/test_handoff_parser.py`

Why this exists. `~/.claude/hooks/session_exchange_handoffs.py` matched entries on `^- _\\(` while
the ledger's documented convention had moved to another shape, so it matched zero entries for ten
days and said nothing, because it exited 0 whether it parsed nothing or there was nothing to parse.
Eighteen entries across two shapes were invisible, measured against the real file on 2026-09-25.
The one assertion that would have caught it is "a section with entries in it yields a non-zero
count", which is the first half of this file.

`fixtures/handoffs.md` is entirely synthetic: fabricated lane names, fabricated Jan 2026 dates, a
fabricated ticket key. Its structure is faithful to the real file and its content has nothing to do
with it, which is the point - the real ledger is in another area and is not read from here. The
replay against the real entries belongs to a session rooted in that area and comes back as counts.
Two of the checks below exist because that replay found defects this fixture did not model.

The script under test is still the live one on one laptop, not a file in this repo: the port lands
with `lib/handoffs.py`, and this regression is what that port has to keep passing. Until then it
points at the live path and skips rather than fails if it is absent, so the suite stays green on a
machine that never had the legacy hooks.
"""

import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "handoffs.md"
SCRIPT = pathlib.Path.home() / ".claude/hooks/session_exchange_handoffs.py"

if not SCRIPT.exists():
    print(f"SKIPPED: {SCRIPT} is not on this machine")
    raise SystemExit(0)

failures = []


def run(ledger, lane_pattern, lane_key="test"):
    """Run the hook the way the wrapper does. Returns (additionalContext, stderr)."""
    env = dict(
        os.environ,
        LEDGER=str(ledger),
        LANE_PATTERN=lane_pattern,
        LANE_KEY=lane_key,
        HOOK_EVENT="SessionStart",
        # The fixture's dates are in Jan 2026 on purpose, so the age filter would aggregate every
        # entry into the "needs archiving" line and list none. Disable both caps for the test.
        OLD_DAYS="100000",
        MAX_LISTED="100",
    )
    done = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True
    )
    if done.returncode != 0:
        return None, done.stderr
    if not done.stdout.strip():
        return "", done.stderr
    payload = json.loads(done.stdout)
    return payload["hookSpecificOutput"]["additionalContext"], done.stderr


def listed(context):
    """Entries actually rendered as open asks, excluding the summary and advisory lines."""
    return [
        line
        for line in (context or "").split("\n")
        if line.strip().startswith("•") and "and " not in line[:14]
    ]


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


print("open handoffs by lane")

# Lane B is the recipient of four open entries: the canonical one-line shape, the multi-recipient
# header, the one whose headline wraps so its status marker sits on the second physical line, and
# the
# prose closure trap below.
context, _ = run(FIXTURE, "Lane B")
check("Lane B sees 4", len(listed(context)), 4)

# Lane G is a recipient twice: once in the multi-recipient header (open), once in a shape B header
# with a free-text recipient that carries a bare `Status: SUPERSEDED` inside the headline's bold.
check("Lane G sees 1", len(listed(run(FIXTURE, "Lane G")[0])), 1)

# Both of Lane H's are closed - one `**Status:** DONE` on a continuation line, one on its own line
# at column 0 immediately below the header. Silence is the correct output, not an empty list.
check("Lane H sees 0, silently", run(FIXTURE, "Lane H")[0], "")

# Lane A is the SENDER on nearly every entry, including a shape B header that names it after
# ", from". A sender must never read as a recipient. The `**↓ tail of ...` continuation marker also
# names Lane A and is not a handoff at all.
check("Lane A sees 0 (sender, not recipient)", run(FIXTURE, "Lane A")[0], "")

print("label spacing drifts between the hardcoded map and the ledger")

# The wrapper's map says "A/B" where the file says "A / B", and vice versa. Both directions have to
# match, because neither side is going to be corrected by hand every time.
check("spaced pattern matches unspaced label", len(listed(run(FIXTURE, "Lane E / F")[0])), 1)
check("unspaced pattern matches spaced label", len(listed(run(FIXTURE, "Lane C/D")[0])), 1)

print("the arrow is not always U+2192")

# One header uses ASCII `->`. It is closed, so the assertion is that it parsed at all: if the entry
# were invisible, its `**Status:** DONE` continuation line would attach to the entry above it and
# that entry would read as closed too, taking Lane B's count down.
context, _ = run(FIXTURE, "Lane B")
check("ASCII arrow entry does not swallow its neighbour", len(listed(context)), 4)

print("prose in a header cannot close an entry")

# Found on a real header during the replay: the docstring promises closure is read only from
# positions that mean "closed", and that held for body lines but not for headers, where the test was
# an unqualified case-insensitive search. A headline saying "no harm done" closed the entry. A false
# closure is indistinguishable from a quiet day at the output, which is the failure this whole
# change
# removes, so it has to stay broken-if-broken rather than silently swallowed.
#
# The keyword has to sit on the fixture entry's HEADER line. A first version of that entry put it on
# the continuation line below, where the header test could never see it: both the broken and the
# fixed
# parser reported 4 and the check passed for the wrong reason. Verified the other way round before
# trusting it - reverting only the header test on a copy takes this count to 3, and the entry that
# disappears is this one.
context, _ = run(FIXTURE, "Lane B")
check(
    '"no harm done" in a headline does not close it',
    any("prose closure trap" in line for line in listed(context)),
    True,
)
# The other direction: lowercase is fine when a `Status:` label qualifies it, so narrowing the
# header
# test to marker spelling must not have broken that.
check(
    "lowercase keyword next to Status: still closes",
    any("2026-01-16" in line for line in listed(context)),
    False,
)

print("fail loud")

# The state that went unnoticed for ten days: a section with content in it, and nothing parsed.
# Built by stripping every entry header out of the fixture and keeping the prose.
prose = "\n".join(
    line
    for line in FIXTURE.read_text().split("\n")
    if not line.startswith("**[") and not line.startswith("**→")
)
loud = HERE / ".tmp-prose-only.md"
loud.write_text(prose)
try:
    context, _ = run(loud, "Lane B")
    check("says so when it parses nothing", "parsed 0 entries" in (context or ""), True)
finally:
    loud.unlink()

# And the state where silence is right: no section at all.
empty = HERE / ".tmp-no-section.md"
empty.write_text("## Something else\n\nNo handoffs section in this file at all.\n")
try:
    check("silent when there is no section", run(empty, "Lane B")[0], "")
finally:
    empty.unlink()

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
