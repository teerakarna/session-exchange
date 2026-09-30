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
# is the whole reason `int()` is in there, and without it a row whose pid arrived as a string reads
# as dead - an int pid signals fine either way, which is what makes this the case worth writing
# down.
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
    # then `continue` becoming `break` leaves the good row already appended and the check passes.
    #
    # Which means this catch depends on the `sorted()` around the glob in `entries`, and that line
    # has no mutation and no check of its own. Recorded rather than fixed, because both obvious
    # fixes are wrong. Adding a second bad file sorting after the good row does nothing: I tried it,
    # and with `sorted()` removed as well the suite stayed green, because raw `glob` order happened
    # to yield `good.json` first and neither bad file preceded it. And no fixture can be made
    # order-independent here - catching `break` needs a bad file read before some good row in
    # *every* possible order, which no set of names guarantees when the order is the filesystem's
    # business. Asserting the read order directly has the same problem from the other end: the only
    # observable it affects is which of two equally-named rows wins a stable-sort tie, so a check on
    # it would pass or fail by filesystem, which is worse than no check.
    #
    # So `sorted()` there is a third category, alongside the unfalsifiable lines noted below:
    # removing it changes no answer this suite can see, and quietly weakens this check. That is
    # written down here because it is the only place it can be, and it is the reason to leave the
    # line alone.
    (sessions / "a-truncated.json").write_text("{ nope")
    (sessions / "a-list.json").write_text('["not a row"]')
    write(sessions, "named-no-id", pid=LIVE, name="no id at all")
    (sessions / "ignored.txt").write_text(json.dumps({"sessionId": "wrong-suffix", "pid": LIVE}))

    # Four files that must not arrive as rows: one that will not parse, one that parses to a list,
    # one with no `sessionId`, and one whose suffix is not `.json`. None of them may take the
    # readable row down with it either. A hook that raises here is a session start that failed, so
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

print("which rows are peers, which is not the same question")

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    # The arrangement measured on this machine when #31 was filed: an interactive session and a
    # background job it spawned, same `name`, different `sessionId`. Rendering both shows two
    # identical rows and invites a reader to coordinate with something that cannot answer.
    write(sessions, 1, sessionId="the-session", pid=LIVE, name="shared", kind="interactive")
    write(sessions, 2, sessionId="the-job", pid=LIVE, name="shared", kind="bg")
    # And a row from the version that has no `kind` field. It counts as a peer: dropping it renders
    # nobody present on that version, which is a worse failure than one row too many, and without
    # this fixture a filter that dropped every unknown kind would pass the check below.
    write(sessions, 3, sessionId="no-kind", pid=LIVE, name="older")

    check(
        "a background job is not a peer",
        [r["sessionId"] for r in registry.entries(sessions)],
        ["no-kind", "the-session"],
    )
    # A set, not a list. The two peer rows share a `name`, so their relative order is a stable-sort
    # tie broken by the read order of the directory, and this file already has a note about not
    # asserting anything that resolves to the filesystem's business.
    check(
        "and comes back when the caller says peerhood is not the question",
        {r["sessionId"] for r in registry.entries(sessions, peers_only=False)},
        {"no-kind", "the-session", "the-job"},
    )
    check("a row with no kind is a peer", registry.is_peer({}), True)
    check("an interactive row is a peer", registry.is_peer({"kind": "interactive"}), True)
    check("a bg row is not", registry.is_peer({"kind": "bg"}), False)
    # A kind nobody here has seen. Kept, and that is the whole reason the predicate is a blocklist:
    # an allowlist would drop whatever Claude Code adds next without saying so, and a session
    # present and unrendered is the failure this project was written about. One row too many is
    # visible.
    check("and a kind nothing here knows about is too", registry.is_peer({"kind": "wat"}), True)

    # `by_session_id` answers "what is this row", so it has to see the job. A filter there returns
    # None for a background job, which is indistinguishable from an id the registry never had - and
    # the caller that most needs the difference is the hook deciding whether to seed a claim.
    job = registry.by_session_id("the-job", sessions)
    check("an identity lookup still resolves a background job", job and job.get("kind"), "bg")

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

    # A row with no name sorts by its id, not by the string "None" that `str(r.get("name"))`
    # produces. A bare `r.get("name")` makes `sorted` raise on the mix of None and str; the string
    # is what the mutation of this line actually does. The id has to sort *after* every name to be
    # visible: "None" is capitalised, so it sorts before every lowercase name, and an id like
    # "aaa-unnamed" lands in the same place the bug does and reads as correct.
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
    # These two were written up as a second unfalsifiable guard, on the grounds that `entries` never
    # yields a row with a falsy `sessionId` so removing `if not session_id` returns None anyway.
    # That is true of the answer and not of the behaviour, and the write-up named the difference
    # without following it: what the guard buys is a directory read skipped, which is observable.
    for empty in ("", None):
        check(
            f"{empty!r} matches nothing rather than the first row",
            registry.by_session_id(empty, sessions),
            None,
        )
    # So here is the observation, and the guard is falsifiable after all. The sentinel is not a
    # path, so `entries` raises on it: with the guard an empty id is answered without the directory
    # ever being reached, and without it the raise is the proof that it was. Asserted because a
    # caller that has no id yet is the ordinary case for a hook whose payload carried none, and
    # doing a directory read per call to return None regardless is the kind of cost nothing would
    # report.
    try:
        unread = registry.by_session_id("", object())
    except Exception as exc:
        unread = f"raised {type(exc).__name__}"
    check("an empty id is answered without reading the directory at all", unread, None)

print("finding the session this process is running inside")


def owner(sessions):
    """`own_entry`'s answer as an id, and the name of the exception if it raised instead."""
    try:
        row = registry.own_entry(sessions)
    except Exception as exc:
        return f"raised {type(exc).__name__}"
    return row and row.get("sessionId")


# The second unfalsifiable line: `own_entry` reads `entries(..., live_only=False)`, and no registry
# row it can match carries a pid that `alive` answers False for, because every pid in the chain came
# out of `ps` as the parent of a live process. Filtering on liveness there would change no answer,
# and no mutation of it would fail, so none is offered. The reason is "no row can carry such a pid"
# rather than "an ancestor is alive", which would conflate existing with signalable: `alive` uses
# signal 0, so it answers False for a process that is running and not ours, and over SSH the chain
# really does contain a root-owned `sshd`.
CHAIN = registry._parents(os.getpid())
# `CHAIN[1]` unguarded is an `IndexError` a dozen checks below here, naming nothing about process
# trees and taking the rest of the file with it. Reachable rather than theoretical: run the suite as
# a container's entry point, which is the natural way to exercise the 3.9 floor without installing a
# 3.9, and the interpreter is pid 1 with no ancestor to find. Named and failed rather than skipped,
# because these checks not having run is exactly what a skip hides.
ANCESTOR = CHAIN[1] if len(CHAIN) > 1 else None

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

if ANCESTOR is None:
    check("this process has an ancestor, or the three checks below cannot run", ANCESTOR, "a pid")
else:
    with tempfile.TemporaryDirectory() as tmp:
        sessions = pathlib.Path(tmp) / "sessions"
        # Only an ancestor has a row, which is the real arrangement: a command run through a tool
        # call is several processes below the session, and matching on its own pid alone finds
        # nothing.
        write(sessions, ANCESTOR, sessionId="above-me", pid=ANCESTOR, name="ancestor")
        check("a row belonging to an ancestor is found by walking up", owner(sessions), "above-me")

    with tempfile.TemporaryDirectory() as tmp:
        sessions = pathlib.Path(tmp) / "sessions"
        # And with both, the nearest one wins. Walking the chain the other way round would hand a
        # nested command the outermost session's row, the wrong session rather than no session.
        write(sessions, LIVE, sessionId="mine", pid=LIVE, name="self")
        write(sessions, ANCESTOR, sessionId="above-me", pid=ANCESTOR, name="ancestor")
        check("the nearest match wins, not the outermost", owner(sessions), "mine")

    with tempfile.TemporaryDirectory() as tmp:
        sessions = pathlib.Path(tmp) / "sessions"
        # The pid as a string, which is how JSON carries whatever was written. `alive` is asserted
        # against exactly this one function up, and `own_entry` builds its own dict of rows keyed on
        # `int(r["pid"])`, so the rule has to hold twice. Every other fixture in this file writes an
        # int, and against an int an int-keyed lookup and a raw-keyed one agree - two inputs that
        # agree cannot say which was read. The row is put on an ancestor rather than on this process
        # because a string pid matching `os.getpid()` would be caught by the nearest-match check
        # above by accident.
        write(sessions, ANCESTOR, sessionId="string-pid", pid=str(ANCESTOR), name="ancestor")
        check("a string pid still matches the chain", owner(sessions), "string-pid")

    with tempfile.TemporaryDirectory() as tmp:
        sessions = pathlib.Path(tmp) / "sessions"
        # Two registry pids in one chain, which is what being inside a background job looks like:
        # the job's own row on this process, and the interactive session that spawned it above.
        # Nearest first would answer with the job, and a claim written from there lands under an id
        # no presence render shows - a write that cannot be read back, and a handoff from a sender
        # nobody can find. Skipping to the interactive ancestor attributes the work to the session
        # a human can reach, which is the same call #31 makes about what a row means.
        write(sessions, LIVE, sessionId="the-job", pid=LIVE, name="shared", kind="bg")
        write(sessions, ANCESTOR, sessionId="the-session", pid=ANCESTOR, name="shared")
        check("own entry skips this process's own background row", owner(sessions), "the-session")
        check(
            "unless asked for the nearest row of any kind, which is what `claim` needs (#68)",
            registry.own_entry(sessions, peers_only=False)["sessionId"],
            "the-job",
        )

with tempfile.TemporaryDirectory() as tmp:
    sessions = pathlib.Path(tmp) / "sessions"
    write(sessions, DEAD, sessionId="theirs", pid=DEAD, name="other")
    check("no matching row is None, not someone else's row", owner(sessions), None)

print("the walk up the process tree")

check("the walk starts with this process", CHAIN[0], os.getpid())
check("and goes further than one level, or it would find nothing", len(CHAIN) > 1, True)
check("nothing in it is pid 1 or below", [p for p in CHAIN if p <= 1], [])
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

# And the other half of the seam, which the two above cannot reach. `explodes` raises whatever it is
# handed regardless of how the call was made, so "a ps that hangs ends the walk" passes whether the
# real call is bounded or not: it asserts the `except` arm, not the thing that gets there. Deleting
# `timeout=5` left all of this green, which is the same defect one layer in - a seam introduced to
# make something assertable, with only the easy side of it asserted.
seen = {}


def record(argv, **kwargs):
    """A stand-in that answers like `ps` and keeps how it was asked."""
    seen["argv"] = argv
    seen.update(kwargs)
    return subprocess.CompletedProcess(argv, 0, "1\n", "")


registry._parents(os.getpid(), run=record)
# Slices and `get` rather than subscripts, for the reason the `alive` loop above gives: where the
# walk ends before it calls `run` at all - a container entry point, pid 1 - `seen` is empty, and a
# subscript here is a KeyError that takes the rest of the file with it rather than four named
# failures. Found by simulating that case, having written the guard for it a few checks up and then
# repeated the mistake.
argv = seen.get("argv", [])
check("the ps call is bounded, not just guarded", seen.get("timeout"), 5)
# Unqualified on purpose, and the module says so at length: /bin/ps on macOS, /usr/bin/ps on most
# Linux, and hardcoding either breaks the other. A claim that load-bearing with nothing reading it
# is how the comment and the code drift apart.
check("ps is left unqualified for PATH to resolve", argv[:1], ["ps"])
# `ppid=` rather than `ppid`: the trailing `=` is what suppresses the header, and without it the
# first line read back is the word PPID, which is not a number and ends the walk at once.
check("and it asks for the parent pid with no header", argv[1:3], ["-o", "ppid="])
check("output is captured rather than inherited", seen.get("capture_output"), True)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
