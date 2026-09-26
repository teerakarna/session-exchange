#!/usr/bin/env python3
"""Claude Code's own session registry, read rather than trusted.

The module had no test file of its own. What coverage it had came through `test_hook.py` and
`test_cli.py`, both of which fake a `HOME` and run a subprocess, so every rule about *which* rows
come back and *in what order* was asserted only where it happened to change a rendered line
somewhere else. A sweep of the module found that out; the checks here are the answer to it.

Two properties carry the weight, and both are about not trusting the file:

- Liveness is checked, never trusted. A registry file can outlive its process, and a row that reads
  as current and is not is worse than no row at all.
- The pid comes from inside the file, never from its name. The two agree today, and depending on a
  filename to carry data is the failure mode this whole plugin exists to replace.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import registry

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def write(sessions, stem, **row):
    """One registry file. `stem` is the filename, which is a pid in the real thing.

    Deliberately not called `name`: a row carries a `name` of its own, and the two are different
    things, which is half of what this file is here to assert.
    """
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{stem}.json").write_text(json.dumps(row), encoding="utf-8")


def reaped():
    """A pid that is definitely not a live process: started, waited for, and reaped."""
    done = subprocess.Popen([sys.executable, "-c", ""])
    done.wait()
    return done.pid


LIVE = os.getpid()
DEAD = reaped()


print("liveness is checked, not trusted")

check("this process is alive", registry.alive(LIVE), True)
check("a reaped process is not", registry.alive(DEAD), False)
# JSON holds whatever was written, and a pid is as likely to arrive as a string as an int. Coercing
# is the whole reason `int()` is in there, and without it every row would read as dead.
check("a pid that arrives as a string is still a pid", registry.alive(str(LIVE)), True)
for junk in (None, "", "not-a-pid", [LIVE]):
    # Called inside a try rather than bare in the argument list, because "and not a crash either"
    # is half of what this asserts and a crash inside `check(...)` never reaches `check`: the name
    # would not print, `failures` would not grow, and the sweep would score the traceback as a
    # catch rather than the assertion.
    try:
        got = registry.alive(junk)
    except Exception as exc:
        got = f"raised {type(exc).__name__}"
    check(f"{junk!r} is not a live process, and not a crash either", got, False)

print("which rows come back")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    write(sessions, LIVE, sessionId="live-one", pid=LIVE, name="bravo")
    write(sessions, DEAD, sessionId="dead-one", pid=DEAD, name="alpha")

    check(
        "a dead session's row is left out by default",
        [r["sessionId"] for r in registry.entries(sessions)],
        ["live-one"],
    )
    # And asked for, it comes back. `by_session_id` depends on this: a session that has just died is
    # exactly the one a caller is trying to resolve a name for.
    check(
        "and comes back when liveness is not the question",
        [r["sessionId"] for r in registry.entries(sessions, live_only=False)],
        ["dead-one", "live-one"],
    )

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    # The filename is a dead pid and the row inside is this process. Included, because the pid is
    # read from the file: name it from the stem and every row in a recycled-pid registry is wrong.
    write(sessions, DEAD, sessionId="from-inside", pid=LIVE, name="alpha")
    check(
        "the pid is read from inside the file, not from its name",
        [r["sessionId"] for r in registry.entries(sessions)],
        ["from-inside"],
    )

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    write(sessions, "good", sessionId="good-one", pid=LIVE, name="zulu")
    # Named to sort before the readable row on purpose. Called `truncated.json` it sorts after, and
    # then skipping the rest of the directory rather than this one file passes just the same.
    (sessions / "a-truncated.json").write_text("{ nope")
    (sessions / "a-list.json").write_text('["not a row"]')
    write(sessions, "nameless-id", pid=LIVE, name="no id at all")
    (sessions / "ignored.txt").write_text(json.dumps({"sessionId": "wrong-suffix", "pid": LIVE}))

    # Four different ways of being unreadable, and none of them is allowed to take the readable row
    # down with it or to arrive as a row. A hook that raises here is a session start that failed, so
    # the raise is caught and named here rather than being allowed to end the file.
    try:
        ids = [str(r.get("sessionId")) for r in registry.entries(sessions)]
    except Exception as exc:
        ids = f"raised {type(exc).__name__}"
    check("an unparseable file is skipped, not fatal", ids, ["good-one"])

    # The argument is documented as a path and arrives as whatever the caller had. Without the
    # coercion the first thing touched is `.is_dir()`, which a string does not have.
    try:
        as_string = [str(r.get("sessionId")) for r in registry.entries(str(sessions))]
    except Exception as exc:
        as_string = f"raised {type(exc).__name__}"
    check("a directory given as a string reads the same", as_string, ["good-one"])

print("in what order, since presence is rendered straight from it")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    # The ids disagree with the names on purpose. Numbered them to match and sorting by either one
    # gives the same answer, so the check passes without saying which field was read.
    write(sessions, 1, sessionId="id-1", pid=LIVE, name="charlie")
    write(sessions, 2, sessionId="id-2", pid=LIVE, name="alpha")
    write(sessions, 3, sessionId="id-3", pid=LIVE, name="bravo")
    check(
        "rows come back by name",
        [r["name"] for r in registry.entries(sessions)],
        ["alpha", "bravo", "charlie"],
    )

    # A row with no name sorts by its id, not by the string "None" that a bare `r.get("name")` key
    # would produce. The id has to sort *after* every name for that to be visible: "None" is
    # capitalised, so it sorts before every lowercase name, and an id like "aaa-unnamed" lands in
    # the same place the bug does and reads as correct.
    write(sessions, 4, sessionId="zulu-unnamed", pid=LIVE)
    check(
        "a row with no name sorts by its id",
        [r.get("name", r["sessionId"]) for r in registry.entries(sessions)],
        ["alpha", "bravo", "charlie", "zulu-unnamed"],
    )

print("a directory that is not there is not an error")

with tempfile.TemporaryDirectory() as tmp:
    # Claude Code creates this directory; a machine where nothing has run yet does not have it,
    # and a hook must not fail a session start over it.
    #
    # No mutation is offered for the `is_dir` guard that serves this, and it is the one line in the
    # module a sweep says nothing about: `glob` on a path that does not exist yields nothing rather
    # than raising, so removing the guard returns the same `[]`. The guard is not unreachable, it
    # is unfalsifiable, which is a different thing from the dead code this repo deletes. It stays
    # as the statement of intent, and this check asserts the contract rather than the line.
    check("no registry at all is no rows", registry.entries(pathlib.Path(tmp) / "never"), [])

print("resolving a known session id")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    write(sessions, LIVE, sessionId="sess-1", pid=LIVE, name="alpha")
    write(sessions, DEAD, sessionId="sess-2", pid=DEAD, name="bravo")

    # `row and row.get(...)` rather than a subscript: under the mutation that makes the lookup miss,
    # a subscript on None raises and the file stops here instead of failing this one check.
    mine = registry.by_session_id("sess-1", sessions)
    check("an id resolves to its row", mine and mine.get("name"), "alpha")
    # The payload carries an id for a session that may already be gone by the time a SessionEnd hook
    # runs, which is the case liveness filtering would silently break.
    gone = registry.by_session_id("sess-2", sessions)
    check(
        "a dead session still resolves, because SessionEnd has to name it",
        gone and gone.get("name"),
        "bravo",
    )
    check("an id nothing carries is None", registry.by_session_id("sess-9", sessions), None)
    # Exact, not a prefix or a substring: two sessions whose ids share a prefix are the normal case,
    # and resolving one to the other would attribute a claim to the wrong session.
    check("a prefix of a real id is not that id", registry.by_session_id("sess", sessions), None)
    # These two are the second unfalsifiable guard, for the same reason as the `is_dir` one above.
    # `entries` never yields a row with a falsy `sessionId`, so removing `if not session_id` returns
    # None anyway: what the guard buys is a directory read skipped, not a different answer. It earns
    # its place the moment the comparison below stops being `==`, which is why both are here.
    for empty in ("", None):
        check(
            f"{empty!r} matches nothing rather than the first row",
            registry.by_session_id(empty, sessions),
            None,
        )

print("finding the session this process is running inside")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"


def owner(sessions):
    """`own_entry`'s answer as an id, and the name of the exception if it raised instead."""
    try:
        row = registry.own_entry(sessions)
    except Exception as exc:
        return f"raised {type(exc).__name__}"
    return row and row.get("sessionId")


# The third unfalsifiable line: `own_entry` reads `entries(..., live_only=False)`, and every pid it
# can match is an ancestor of a live process and therefore alive. Filtering on liveness there would
# change no answer. It is honest about not caring rather than relying on that, and no mutation of it
# would fail, so none is offered.
ANCESTOR = registry._parents(os.getpid())[1]

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    write(sessions, LIVE, sessionId="mine", pid=LIVE, name="self")
    write(sessions, DEAD, sessionId="theirs", pid=DEAD, name="other")
    check("own entry is this process's row", owner(sessions), "mine")

    # A row whose pid is not a number is skipped rather than crashing the lookup, and a `pid` key
    # that is missing entirely is the same case. Either would take out every command that needs to
    # know who it is, which is all of them.
    write(sessions, "junk", sessionId="junk-pid", pid="not-a-number", name="junk")
    write(sessions, "absent", sessionId="no-pid", name="absent")
    check("a row with an unusable pid is skipped", owner(sessions), "mine")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    # Only an ancestor has a row, which is the real arrangement: a command run through a tool call
    # is several processes below the session, and matching on its own pid alone finds nothing.
    write(sessions, ANCESTOR, sessionId="above-me", pid=ANCESTOR, name="ancestor")
    check("a row belonging to an ancestor is found by walking up", owner(sessions), "above-me")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    # And with both, the nearest one wins. Walking the chain the other way round would hand a nested
    # command the outermost session's row, which is the wrong session rather than no session.
    write(sessions, LIVE, sessionId="mine", pid=LIVE, name="self")
    write(sessions, ANCESTOR, sessionId="above-me", pid=ANCESTOR, name="ancestor")
    check("the nearest match wins, not the outermost", owner(sessions), "mine")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    write(sessions, DEAD, sessionId="theirs", pid=DEAD, name="other")
    check("no matching row is None, not someone else's row", owner(sessions), None)

print("the walk up the process tree")

chain = registry._parents(os.getpid())
check("the walk starts with this process", chain[0], os.getpid())
check("and goes further than one level, or it would find nothing", len(chain) > 1, True)
check("nothing in it is pid 1 or below", [p for p in chain if p <= 1], [])
# Bounded, so a cycle or a lying `ps` cannot hang a command. Asserted at 2 rather than at the
# default, because the real depth varies by how the suite was invoked.
check("the limit is a limit", len(registry._parents(os.getpid(), limit=2)), 2)
check("a pid with no parent to walk to is an empty chain", registry._parents(1), [])
# `ps` prints nothing at all for a pid it does not know, and the empty string is not a number. The
# walk ends there rather than trying to turn it into one, which is the `int()` below it raising.
try:
    unknown = registry._parents(DEAD)
except Exception as exc:
    unknown = f"raised {type(exc).__name__}"
check("a pid ps knows nothing about ends the walk", unknown, [DEAD])


def explodes(exc):
    """A stand-in for `subprocess.run` that fails the way a real `ps` call can."""

    def run(*args, **kwargs):
        raise exc

    return run


# The two real failures, neither reachable on a machine with a working `ps`, which is why the seam
# exists. Both have to end the walk holding what it already had: `own_entry` then finds no row and
# every command falls back to saying so, rather than a hook raising on a session start.
for label, boom in (
    ("no ps on PATH", FileNotFoundError("ps")),
    ("a ps that hangs", subprocess.TimeoutExpired(cmd=["ps"], timeout=5)),
):
    try:
        got = registry._parents(os.getpid(), run=explodes(boom))
    except Exception as exc:
        got = f"raised {type(exc).__name__}"
    check(f"{label} ends the walk rather than raising", got, [os.getpid()])

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
