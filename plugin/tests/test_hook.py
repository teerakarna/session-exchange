#!/usr/bin/env python3
"""The hook, end to end, as a subprocess with a synthetic HOME.

Run as a real process against real files, because the thing being asserted is what Claude Code
receives on stdout and what ends up on disk, and an in-process call proves neither.

`HOME` is the whole test fixture: the legacy scripts, the settings that wire them and the session
registry are all found relative to it, so pointing it at a tmpdir isolates every one of them without
the plugin needing a test-only switch to let it happen.

The two assertions that matter most are the negative ones. A migration warning that fires
unconditionally would satisfy every positive check here, and so would a hook that injects something
on every session regardless of whether there is anything to say.
"""

import io
import json
import os
import pathlib
import pty
import subprocess
import sys
import tempfile

LIB = pathlib.Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

# A wiring in the shape of the one being replaced. The lane argument is invented: the point of
# the assertion below is that this string never reaches the injected context.
LEGACY_COMMAND = 'bash "$HOME/.claude/hooks/session-exchange-active-now.sh" a-lane-arg'

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def fixture(tmp, *, wire_legacy, wire_under_root=False):
    """A synthetic HOME, a marked root, and a repo inside it.

    `wire_legacy` wires the user's own settings, which is a machine-wide wiring: it fires for every
    session on the machine whatever root that session belongs to. `wire_under_root` wires a
    `settings.local.json` under the root instead, which fires for this root only. The two are
    different faults and the hook says different things about them, so a fixture that can only
    produce one of them can only ever assert half of it - which is how the machine-wide case came to
    be asserted as a doubled fire for as long as it was.
    """
    tmp = pathlib.Path(tmp).resolve()
    home = tmp / "home"
    hooks = home / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (home / ".claude" / "sessions").mkdir()

    # Shaped like the scripts being replaced. Named by shape rather than copied: the real pair
    # carries one environment's project prefix and this repo does not take that on.
    (hooks / "session_exchange_handoffs.py").write_text("# legacy\n")
    (hooks / "session-exchange-active-now.sh").write_text("# legacy\n")
    # Present, unrelated, and must not be mistaken for legacy. Without this the globs could match
    # anything and every positive check below would still pass.
    (hooks / "review-requests-check.sh").write_text("# unrelated, working, staying\n")

    wiring = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": LEGACY_COMMAND,
                        }
                    ]
                }
            ]
        }
    }
    (home / ".claude" / "settings.json").write_text(
        json.dumps(wiring if wire_legacy else {"hooks": {}})
    )

    root = tmp / "area"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "exchange.json").write_text(json.dumps({"name": "area"}))
    if wire_under_root:
        (root / ".claude" / "settings.local.json").write_text(json.dumps(wiring))
    repo = root / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return home, root, repo


def run(event, payload, home, env=None, cwd=None):
    """Fire the hook. Returns `(exit code, injected context or None)`.

    `cwd` is the process's own working directory, which only matters for the one case where the
    payload does not carry one and the module has to fall back to it.
    """
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    environ.update(env or {})
    done = subprocess.run(
        [sys.executable, str(LIB / "hook.py"), event],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=environ,
        cwd=None if cwd is None else str(cwd),
        timeout=30,
    )
    if not done.stdout.strip():
        return done.returncode, None
    return done.returncode, json.loads(done.stdout)


print("session start, with a legacy hook still wired")

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    code, out = run(
        "SessionStart",
        {
            "hook_event_name": "SessionStart",
            "session_id": "sess-1",
            "cwd": str(repo),
            "source": "startup",
        },
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")

    check("exits 0", code, 0)
    check(
        "echoes back the event that fired",
        (out or {}).get("hookSpecificOutput", {}).get("hookEventName"),
        "SessionStart",
    )
    # The wiring here is in the user's own settings, so what it warns about is a hook that fires for
    # every session on this machine - not this root being rendered twice. Asserted as a pair so that
    # the two cannot silently collapse back into one message: the machine-wide half read as a
    # doubled fire until a real migration showed a session handed another root's rows.
    check(
        "warns that a legacy hook is wired machine-wide, and does not call it a doubled fire",
        ("wired machine-wide" in context, "rendered twice" in context),
        (True, False),
    )
    check("names the wired script", "session-exchange-active-now.sh" in context, True)
    # The one on disk but not wired is inert, so it is not what the warning is about.
    check(
        "does not name a script that is only on disk",
        "session_exchange_handoffs.py" in context,
        False,
    )
    check("does not mistake an unrelated hook for legacy", "review-requests" in context, False)
    check(
        "says nothing about the command string it found the wiring in",
        "a-lane-arg" in context,
        False,
    )

    claim = root / ".claude" / "exchange" / "sessions" / "sess-1.json"
    check("seeded a claim under the root, not under the repo", claim.is_file(), True)
    written = json.loads(claim.read_text())
    check(
        "the claim knows where the session is and on what branch",
        (written["cwd"], written.get("git_branch")),
        (str(repo), "main"),
    )

    print("session end")
    code, out = run(
        "SessionEnd",
        {
            "hook_event_name": "SessionEnd",
            "session_id": "sess-1",
            "cwd": str(repo),
            "reason": "clear",
        },
        home,
    )
    check("exits 0 and says nothing", (code, out), (0, None))
    check("the claim is gone, with nobody having had to remember", claim.exists(), False)

print("session start, with a legacy hook wired under this root")

with tempfile.TemporaryDirectory() as tmp:
    # The other fault: a wiring in a `settings.local.json` under the root fires for this root, so
    # this root really is rendered twice. Nothing machine-wide here, which is the half that has to
    # stay out of the message - a session told both things at once learns neither.
    home, root, repo = fixture(tmp, wire_legacy=False, wire_under_root=True)
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-4", "cwd": str(repo)},
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check(
        "warns that this root is rendered twice, and says nothing about machine-wide",
        ("rendered twice" in context, "machine-wide" in context),
        (True, False),
    )
    check("and names the script it found", "session-exchange-active-now.sh" in context, True)

print("session start, with one wired each way")

with tempfile.TemporaryDirectory() as tmp:
    # Both faults at once, which is the state a half-finished step 7 leaves, and the only one where
    # the two warnings can be told apart by what they name. Two different scripts on purpose: with
    # the same one wired twice, a warning naming everything it found reads identically to one naming
    # only its own half, and two inputs that agree cannot say which was read.
    home, root, repo = fixture(tmp, wire_legacy=True, wire_under_root=True)
    (root / ".claude" / "settings.local.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'bash "$HOME/.claude/hooks/alpha-session-lane.sh"',
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-5", "cwd": str(repo)},
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    doubled = [line for line in context.splitlines() if "rendered twice" in line]
    crossing = [line for line in context.splitlines() if "machine-wide" in line]
    check(
        "both faults are warned about, not the first one found",
        (len(doubled), len(crossing)),
        (1, 1),
    )
    check(
        "the doubled-fire line names only the wiring under this root",
        doubled
        and (
            "alpha-session-lane.sh" in doubled[0],
            "session-exchange-active-now.sh" in doubled[0],
            "1 legacy hook" in doubled[0],
        ),
        (True, False, True),
    )
    check(
        "and the machine-wide line names only the one in the user's own settings",
        crossing
        and (
            "session-exchange-active-now.sh" in crossing[0],
            "alpha-session-lane.sh" in crossing[0],
        ),
        (True, False),
    )

print("session start, with nothing wired and nothing wrong")

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run(
        "SessionStart",
        {
            "hook_event_name": "SessionStart",
            "session_id": "sess-2",
            "cwd": str(repo),
        },
        home,
    )
    # Break it: the warning above must be conditional. An unconditional one passes every positive
    # check and turns the injected section into something a reader learns to skip.
    check("injects nothing at all", (code, out), (0, None))
    check(
        "but still seeded the claim",
        (root / ".claude" / "exchange" / "sessions" / "sess-2.json").is_file(),
        True,
    )

print("a store with something wrong in it, which the session is told about")

with tempfile.TemporaryDirectory() as tmp:
    # #32. `show` named these by filename and the hook said nothing, so the one place every session
    # is guaranteed to look was the one place a corrupt store was invisible. Both record types,
    # because claims were what the issue reported and the handoff half is the same silence one
    # directory over.
    home, root, repo = fixture(tmp, wire_legacy=False)
    exchange = root / ".claude" / "exchange"
    (exchange / "sessions").mkdir(parents=True, exist_ok=True)
    (exchange / "handoffs").mkdir(parents=True, exist_ok=True)
    (exchange / "sessions" / "wrecked.json").write_text("{ not json")
    (exchange / "handoffs" / "20260101T000000Z-aaaaaa.json").write_text(
        json.dumps({"id": "20260101T000000Z-aaaaaa", "status": "closed"})
    )
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-corrupt", "cwd": str(repo)},
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check("an unreadable claim is named, by the filename it is in", "wrecked.json" in context, True)
    check(
        "and an invalid handoff record too, not only the claims",
        "20260101T000000Z-aaaaaa.json" in context,
        True,
    )
    # Rule 2. A fault in the store is somebody else's record being wrong, not this session failing.
    check("and the session still starts", code, 0)
    check(
        "and it still seeded its own claim",
        (root / ".claude" / "exchange" / "sessions" / "sess-corrupt.json").is_file(),
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    # Past the cap the remainder is counted rather than dropped. A report that quietly stops at
    # three reads exactly like a store with three faults in it, which is this repo's recurring
    # shape.
    home, root, repo = fixture(tmp, wire_legacy=False)
    sessions = root / ".claude" / "exchange" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    for n in range(6):
        (sessions / f"wrecked-{n}.json").write_text("{ not json")
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-many", "cwd": str(repo)},
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check("six faults are not six lines", context.count("wrecked-"), 3)
    check("and the remainder is counted", "3 more problem(s)" in context, True)
    check("and names where to read the rest", "`exchange show`" in context, True)

with tempfile.TemporaryDirectory() as tmp:
    # The negative half, which is the one that matters: a store with nothing wrong in it says
    # nothing. Every check above passes just as well against a hook that reports unconditionally.
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-clean", "cwd": str(repo)},
        home,
    )
    check("a store with nothing wrong in it injects nothing", (code, out), (0, None))

print("rule 3: no root, no output, no files")

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    outside = pathlib.Path(tmp) / "elsewhere"
    outside.mkdir()
    code, out = run(
        "SessionStart",
        {
            "hook_event_name": "SessionStart",
            "session_id": "sess-3",
            "cwd": str(outside),
        },
        home,
    )
    check("silent where there is no exchange", (code, out), (0, None))
    check("and creates nothing", list(outside.iterdir()), [])

print("a root that was pointed at deliberately and is wrong")

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
        env={"CC_EXCHANGE_ROOT": str(pathlib.Path(tmp) / "nowhere")},
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check(
        "says so rather than falling back to the walk",
        (code, "CC_EXCHANGE_ROOT" in context),
        (0, True),
    )
    # `problem()` existed to mark its own output in a wall of context somebody else also writes to,
    # and nothing asserted the mark: the whole body could be `return text` and the suite stayed
    # green. Asserted on a live path rather than on the function, because the thing that matters is
    # that the prefix survives to the reader.
    check("and marks the line as coming from this plugin", "[session-exchange]" in context, True)

print("what session start does when a step of it goes wrong")

# Seven rules in `hook.py` with nothing behind them, every one found by sweeping the module rather
# than by reading it, and all of them the same shape: a problem gets computed correctly and then
# dropped. The suite had no case for it because every run in it was a run where nothing went wrong -
# which is the comfortable half to write and the half that asserts least.

# A claim that could not be written, because a payload with no session id has nothing to name the
# file after. Without the line, the session starts looking exactly like one that is on the board.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run("SessionStart", {"hook_event_name": "SessionStart", "cwd": str(repo)}, home)
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check("a claim that could not be seeded says so", "session id" in context, True)
    check("and the session still starts", code, 0)

# The registry is the only place a display name comes from: the payload has no such field, so a
# claim seeded without the lookup is a row every other session sees as a bare id. `pid` is this
# process because the lookup is by id and does not care, but a row without one is skipped.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    (home / ".claude" / "sessions" / "reg.json").write_text(
        json.dumps({"sessionId": "sess-named", "name": "macgyver-2", "pid": os.getpid()})
    )
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-named", "cwd": str(repo)},
        home,
    )
    seeded = root / ".claude" / "exchange" / "sessions" / "sess-named.json"
    check(
        "the claim carries the name the registry knows this session by",
        json.loads(seeded.read_text()).get("name"),
        "macgyver-2",
    )

# A background job fires SessionStart with an id of its own, and it is not a second session.
# Seeding for it gives the root two claims for what the user sees as one, both carrying the same
# registry `name`, and `SessionEnd` clears only the one that ended - so the leftover renders as a
# peer with a duplicate name and nothing says which is which. Live on this machine when #31 was
# measured: two rows for one session, same name, different ids. Both halves are asserted: no claim
# written, and nothing injected either, with the legacy wiring in place so "nothing injected" is a
# real answer rather than the answer this fixture gives anyway.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    (home / ".claude" / "sessions" / "bg.json").write_text(
        json.dumps(
            {"sessionId": "sess-bg", "name": "shared-name", "pid": os.getpid(), "kind": "bg"}
        )
    )
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-bg", "cwd": str(repo)},
        home,
    )
    check(
        "a background job seeds no claim of its own",
        (root / ".claude" / "exchange" / "sessions" / "sess-bg.json").is_file(),
        False,
    )
    check("and injects nothing into a context it shares with its session", out, None)
    check("and the session still starts", code, 0)

    # The same fixture with the kind removed, which is the version of Claude Code that predates the
    # field. It has to seed: treating an unknown kind as not-a-peer renders nobody present at all,
    # which is worse than rendering one row too many. Without this check the guard above passes just
    # as well when it drops every session on that version.
    (home / ".claude" / "sessions" / "bg.json").write_text(
        json.dumps({"sessionId": "sess-nokind", "name": "shared-name", "pid": os.getpid()})
    )
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-nokind", "cwd": str(repo)},
        home,
    )
    check(
        "a row with no kind at all is still a session",
        (root / ".claude" / "exchange" / "sessions" / "sess-nokind.json").is_file(),
        True,
    )

# A marker that exists and does not parse is still a root, because `resolve` only asks whether the
# file is there. So the run continues on defaults, and this line is the only thing between that and
# a correctly configured exchange - a cap read as its default is not visibly a cap not read at all.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    (root / ".claude" / "exchange.json").write_text("{ not json")
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check(
        "config that could not be read is reported, not defaulted over",
        "exchange.json" in context,
        True,
    )

# A settings file that could not be read is not a settings file with nothing wired in it, and the
# difference lands harder here than anywhere: the whole double-fire answer is only as good as the
# files the scan managed to open.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    (root / ".claude" / "settings.local.json").write_text("{ not json")
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check(
        "whatever else the scan could not do is injected too",
        "wiring there is unknown" in context,
        True,
    )

# One script, wired in two settings files, is one script. Counted as a list it reads "2 legacy hook
# script(s) still wired" and names the same file twice, which is a migration report nobody can act
# on: the reader goes looking for a second wiring that is not there.
#
# Both wirings have to sit in the same bucket for this to be the assertion it is meant to be. With
# one machine-wide and one under the root, the script is named once per warning because it is two
# faults, and counting two names would be counting the two warnings rather than the dedupe.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False, wire_under_root=True)
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.local.json").write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": LEGACY_COMMAND}]}]}}
        )
    )
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check("the same script wired in two files is counted once", "1 legacy hook" in context, True)
    check("and named once", context.count("session-exchange-active-now.sh"), 1)

# `cwd` is in every real payload, so the fallback only matters when one arrives malformed - and with
# it gone that is a TypeError out of `resolve`, which the catch-all in `main` turns into a line
# about the hook instead of a session that started and got itself on the board.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run(
        "SessionStart",
        {"hook_event_name": "SessionStart", "session_id": "sess-cwd"},
        home,
        cwd=repo,
    )
    check("a payload with no cwd falls back to where the process is", (code, out), (0, None))
    check(
        "and the claim it seeded says where that was",
        json.loads((root / ".claude" / "exchange" / "sessions" / "sess-cwd.json").read_text())[
            "cwd"
        ],
        str(repo),
    )

print("session end, when the claim will not clear")

# The one rule in `session_end`, and the comment in the module says why it is worth a line nobody
# may read: a claim that outlives its session shows up to everybody else as a live peer.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run("SessionEnd", {"hook_event_name": "SessionEnd", "cwd": str(repo)}, home)
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check("a claim that could not be cleared says so", "session id" in context, True)
    check("and the session still ends cleanly", code, 0)

print("wired under an event the plugin does not handle")

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run("Stop", {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo)}, home)
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check(
        "reports the mismatch instead of doing nothing quietly",
        (code, "does not handle" in context),
        (0, True),
    )
    check(
        "and replies under the event that actually fired",
        (out or {}).get("hookSpecificOutput", {}).get("hookEventName"),
        "Stop",
    )

print("the payload disagrees with the wiring about which event fired")

# The rule `hookio` exists to enforce, and until this section there was no check behind it: every
# other case here passes the same event name in argv and in the payload, so the whole suite stayed
# green with `event_name` reduced to `return default`. That is the defect that made one lane's
# handoffs invisible, reintroducible without a single failing test.
#
# Legacy wiring is on so that the run has something to inject. A reply only exists when there is a
# line to put in it, which is `emit`'s own rule, so an event name cannot be read off a session that
# correctly said nothing.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    code, out = run(
        "Stop",
        {
            "hook_event_name": "SessionStart",
            "session_id": "s",
            "cwd": str(repo),
            "source": "startup",
        },
        home,
    )
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check(
        "the payload wins, so the reply is one Claude Code will accept",
        (out or {}).get("hookSpecificOutput", {}).get("hookEventName"),
        "SessionStart",
    )
    # Which handler ran is the other half: echoing the right name while running the wrong handler
    # would satisfy the check above and still do nothing.
    check(
        "and the payload's handler ran, not the one argv named",
        (code, "does not handle" in context),
        (0, False),
    )

print("the payload does not say which event fired")

# The fallback, and the reason `event_name` takes a default at all. Without this, the rule above
# could be satisfied by dropping the default entirely, which turns a missing field into a reply
# addressed to `None` and no injected context at all.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    code, out = run("Stop", {"session_id": "s", "cwd": str(repo)}, home)
    context = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check(
        "the wiring is the fallback, and it still replies under a real event name",
        (
            (out or {}).get("hookSpecificOutput", {}).get("hookEventName"),
            "does not handle" in context,
        ),
        ("Stop", True),
    )

# A non-string is the same case as absent: the field cannot be echoed back, and a reply whose event
# name is a number is dropped without comment.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    code, out = run(
        "SessionStart", {"hook_event_name": 7, "session_id": "s", "cwd": str(repo)}, home
    )
    check(
        "a payload event that is not a string falls back too",
        (out or {}).get("hookSpecificOutput", {}).get("hookEventName"),
        "SessionStart",
    )

print("stdin is not JSON at all")

# `payload()` is called *outside* `main`'s try block, so its own swallowing of a bad parse is the
# only thing between a malformed payload and a traceback on a non-zero exit - which is precisely
# what rule 2 says a hook must never do. Nothing asserted it until here.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    done = subprocess.run(
        [sys.executable, str(LIB / "hook.py"), "SessionStart"],
        input="not json {",
        capture_output=True,
        text=True,
        env=environ,
        # Inside the fixture, because a payload that does not parse carries no `cwd` either, so the
        # root walk starts from the process's own directory. Left alone it starts in the repo and
        # walks the real filesystem, which is the one thing this file's HOME substitution is for.
        cwd=str(tmp),
        timeout=30,
    )
    check(
        "exits 0 with nothing on stderr rather than reporting a parse it cannot reply to",
        (done.returncode, done.stderr.strip()),
        (0, ""),
    )

print("stdin is JSON, but not an object")

# Valid JSON and still unusable, which the parse guard above does not cover: a non-object gets
# through `json.loads` and then every `.get` on it raises, outside `hook.main`'s own try block.
# Exit 1 with a traceback on a SessionStart hook is the one thing this plugin says it will never do,
# and it was two characters away with the whole suite green.
#
# Every JSON type, not just `null`. The first fix here was `or {}` and the first check was `null`,
# which is the one truthy-test case `or {}` happens to handle - so the check was green while `5`,
# `true`, `"x"` and `[1]` all still exited 1. One example per branch of a guard is not a test of the
# guard, it is a test of the example, and this is the second time in this diff that agreement
# between a check and a fix hid the rest of the rule.
for literal in ("null", "5", "true", '"x"', "[1]", "[]"):
    with tempfile.TemporaryDirectory() as tmp:
        home, root, repo = fixture(tmp, wire_legacy=True)
        environ = dict(os.environ, HOME=str(home))
        environ.pop("CC_EXCHANGE_ROOT", None)
        done = subprocess.run(
            [sys.executable, str(LIB / "hook.py"), "SessionStart"],
            input=literal,
            capture_output=True,
            text=True,
            env=environ,
            cwd=str(tmp),  # Same reason as above: no payload means no `cwd` in it.
            timeout=30,
        )
        check(
            f"a payload of {literal} is the same as no payload, not a traceback",
            (done.returncode, done.stderr.strip()),
            (0, ""),
        )

print("stdin is not open at all")

# The same guarantee through the real process, for an input that has no `read` rather than the
# wrong kind of payload. Reached by closing fd 0, which `subprocess` has no argument for: `DEVNULL`
# is an open fd that reads as empty, and the parse guard covers that already. So a one-line
# interpreter closes it and execs the hook, rather than a shell doing the same with a redirect.
# Found by running the handler this way, not by reading the module: it exited 1 with an
# AttributeError traceback out of `main` while every check above was green.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    hook_py = str(LIB / "hook.py")
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os;os.close(0);"
            f"os.execv({sys.executable!r},[{sys.executable!r},{hook_py!r},'SessionStart'])",
        ],
        capture_output=True,
        text=True,
        env=environ,
        cwd=str(tmp),
        timeout=30,
    )
    check(
        "a closed stdin is no payload, rather than a traceback out of main",
        (done.returncode, done.stderr.strip()),
        (0, ""),
    )

print("stdin is a terminal, because somebody ran the handler by hand")

# The guard whose absence is a hang rather than a wrong answer, which is why it needs a pty to
# assert at all: with no payload coming, `read()` on a terminal waits forever, and a SessionStart
# hook that never returns is a session that never starts. A timeout is caught and reported as a
# failure rather than left to propagate, because a test that dies mid-run names nothing.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=True)
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    controller, follower = pty.openpty()
    try:
        done = subprocess.run(
            [sys.executable, str(LIB / "hook.py"), "SessionStart"],
            stdin=follower,
            capture_output=True,
            text=True,
            env=environ,
            cwd=str(tmp),  # And here, where there is no payload at all.
            timeout=15,
        )
        result = done.returncode
    except subprocess.TimeoutExpired:
        result = "hung waiting for a payload that a terminal is never going to send"
    finally:
        os.close(follower)
        os.close(controller)
    check("returns instead of waiting on a payload nobody is going to type", result, 0)

print("what emit does with the lines it is given")

import hookio  # noqa: E402

# Two rules of `emit` that no end-to-end case reaches, because every one of them happens to inject a
# single line. Joining with a space instead of a newline, and dropping the empty-line filter, both
# left the suite green. A unit check is the honest place for them: composing a hook run that emits
# three lines including a blank one would be testing the caller, not the join.


def injected(lines):
    """What `emit` would inject for these lines, or a description of why there is nothing.

    Not `json.loads(sink.getvalue())`. A regression that makes `emit` go quiet leaves that empty,
    the parse raises at module level, and this file stops before the three rule-2 checks below - so
    the mutation scores as caught by a crash that took its neighbours with it. The comment under
    the next call warns about that shape for the `None` case; this is the same hazard through the
    output rather than the input.
    """
    sink = io.StringIO()
    hookio.emit("SessionStart", lines, out=sink)
    raw = sink.getvalue()
    if not raw.strip():
        return "nothing was injected at all"
    try:
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    except Exception as exc:
        return f"the reply was not the shape a hook reply has: {type(exc).__name__}"


check(
    "lines are separated by a newline, not run together",
    injected(["first", "second"]),
    "first\nsecond",
)

# A bare `""` and not a `None` alongside it. `None` would make the unfiltered case raise inside
# `"\n".join` rather than return a wrong answer, so the mutation would score as caught by a crash
# rather than by this assertion.
check(
    "an empty line is dropped rather than injected as a gap",
    injected(["first", "", "second"]),
    "first\nsecond",
)

# The narrowing on the redirect below, which `if True:` satisfied with the whole suite green. `out=`
# is a test seam, and pointing fd 1 at devnull because a caller's in-memory stream would not flush
# is a guess dressed as a guard: the caller keeps its own stdout.


class FlushFails(io.StringIO):
    """A handed-in stream that raises where a dead pipe raises, in memory."""

    def flush(self):
        raise OSError("no reader here either")


def fd1_across_a_failed_flush():
    """What became of fd 1 when `emit` was handed a stream that will not flush.

    fd 1 is saved and put back around the call, and the comparison is made before it is put back.
    Without that, the regression this exists for reports nothing: `if True:` makes `emit` dup2
    devnull onto fd 1, `sys.stdout` still holds fd 1, and every `check` below prints into the dark.
    Measured, rather than reasoned about - the file went to zero bytes on stdout, zero on stderr and
    exit 1, so the sweep scored it as caught by a file that crashed rather than by this rule, and
    roughly a hundred and fifty later checks went dark with it.

    Shielded for the same reason `injected` and `read_by` are. `FlushFails` exists to make `emit`'s
    guard fire, so any change to that guard raises here, at module level, and would take the three
    end-to-end checks below with it.

    fd 1 by identity rather than by name, and a run where it is already devnull is reported as
    proving nothing rather than passing: under `run.py` it is a pipe, but a suite run with stdout
    sent to devnull by hand would otherwise be green for the wrong reason.
    """
    saved = os.dup(1)
    try:
        before = os.fstat(1)
        try:
            hookio.emit("SessionStart", ["a line"], out=FlushFails())
        except Exception as exc:
            return f"emit raised {type(exc).__name__}"
        after = os.fstat(1)
        null = os.stat(os.devnull)
        if (before.st_dev, before.st_ino) == (null.st_dev, null.st_ino):
            return "fd 1 was already devnull, so this proves nothing"
        same = (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    finally:
        os.dup2(saved, 1)
        os.close(saved)
    return "fd 1 is untouched" if same else "fd 1 was redirected"


check(
    "a stream the caller handed in never gets fd 1 redirected out from under it",
    fd1_across_a_failed_flush(),
    "fd 1 is untouched",
)

print("and a reader that has gone away does not take the session down with it")

# The module docstring calls the guarantee absolute: anything that goes wrong becomes a line of
# injected context and an exit status of 0. It held for every input and not for every *reader*. With
# the read end of stdout closed before the hook writes, the process exited 120 with a
# `BrokenPipeError` on stderr - and not from the `print`, which returns fine. The bytes sat in the
# buffer and the interpreter's own shutdown flush was what failed, after `main` had already returned
# 0, where nothing can catch it.
#
# End to end against the real handler rather than through `emit(out=...)`, because the whole failure
# is in a real fd and a real buffer. An in-memory sink cannot have a reader that went away, so a
# unit check here would pass against the broken version.
#
# Three states of it, not one. The first fix here guarded the flush, this file asserted the buffered
# pipe, and the docstring claimed every reader - which is the `or {}` shape from CONTRIBUTING.md, a
# check fed back exactly the input that showed the bug and reading as cover for the rest of the
# rule. The other two both still exited 1 with a traceback: unbuffered, the write raises during the
# `print` rather than in the shutdown flush, and with fd 1 closed CPython puts `None` in
# `sys.stdout`, so the flush is an AttributeError. All three reach a real session -
# `PYTHONUNBUFFERED` in somebody's environment is enough for the second.
#
# The read end is closed before the process starts, so the write is broken from its first byte and
# there is no race to lose.


def run_into_a_dead_pipe(event, payload, home, env=None, close_stdout=False):
    """Fire the hook with no reader on stdout. Returns `(exit code, stderr)`.

    `close_stdout` is fd 1 gone rather than merely unread, which `subprocess` has no argument for -
    `DEVNULL` is an open fd. Same trick as the closed-stdin check above: a one-line interpreter
    closes it and execs the hook.
    """
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    # Scrubbed for the same reason `CC_EXCHANGE_ROOT` is, and it matters more. Exported in the
    # shell, it makes the block-buffered case below a second copy of the unbuffered one, and then
    # removing the whole `dup2` body leaves every check here green - the central fix of this change
    # unasserted, and the sweep naming a live rule as untested. Nothing in `ci.yml` sets it, which
    # is the green-CI-is-necessary-but-not-sufficient case again: the hole only opens on a machine.
    environ.pop("PYTHONUNBUFFERED", None)
    environ.update(env or {})
    if close_stdout:
        hook_py = str(LIB / "hook.py")
        argv = [
            sys.executable,
            "-c",
            "import os;os.close(1);"
            f"os.execv({sys.executable!r},[{sys.executable!r},{hook_py!r},{event!r}])",
        ]
        stdout = subprocess.DEVNULL
    else:
        argv = [sys.executable, str(LIB / "hook.py"), event]
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        stdout = write_fd
    try:
        done = subprocess.run(
            argv,
            input=json.dumps(payload),
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=True,
            env=environ,
            timeout=30,
        )
    finally:
        if not close_stdout:
            os.close(write_fd)
    return done.returncode, done.stderr


# Legacy wiring in every case, so there is a line to inject. With nothing to say `emit` returns
# before it writes, and every check below would pass on any version of this module.
for label, env, closed in (
    ("whose reader has closed stdout", None, False),
    ("writing unbuffered into the same dead pipe", {"PYTHONUNBUFFERED": "1"}, False),
    ("with no stdout at all", None, True),
):
    with tempfile.TemporaryDirectory() as tmp:
        home, root, repo = fixture(tmp, wire_legacy=True)
        code, err = run_into_a_dead_pipe(
            "SessionStart",
            {
                "hook_event_name": "SessionStart",
                "session_id": "sess-dead-pipe",
                "cwd": str(repo),
                "source": "startup",
            },
            home,
            env=env,
            close_stdout=closed,
        )
        # Both halves, and stderr is the half that matters more. `session-start.sh` ends
        # `|| exit 0`, so the exit status never reached Claude Code; the traceback did, and the
        # module docstring calls that louder and less useful than the problem it reports.
        check(f"a hook {label} still exits 0", code, 0)
        check(f"and a hook {label} leaves nothing on stderr", err, "")
        # And still did the work, which is the half a user notices. The reply is dropped by design
        # when there is no stdout to put it on, so without this a future early return further up -
        # in `hook.main` rather than in `emit` - would stop seeding claims with both checks above
        # green, and "silence, not a traceback" would have become silence and nothing else.
        check(
            f"and a hook {label} still seeded its claim",
            (root / ".claude" / "exchange" / "sessions" / "sess-dead-pipe.json").is_file(),
            True,
        )

print("what payload does with a stream it is handed")

# The other half of a pair this file only asserted one side of. `emit` takes `out=` and is checked
# through it; `payload` takes `stream=` and nothing had ever passed one, so the parameter could be
# reduced to `stream = sys.stdin` with the suite green - a parameter with no user is not a seam, it
# is decoration that reads like one.
#
# `sys.stdin` is swapped for an empty stream across the calls rather than left alone. A version that
# ignores the argument would fall back to the real stdin, and the real stdin under a test runner is
# whatever the runner was launched with: a pipe nobody is writing to blocks, and a sweep scores a
# hang as a survivor rather than as a catch. Substituted, the wrong answer is `{}` and arrives at
# once.


def read_by(stream):
    """What `payload` makes of this stream, or the name of the exception it let escape.

    Same reasoning as `injected`: the regressions these checks are for are exceptions, and an
    exception at module level stops the file before everything below it, so the mutation scores as
    caught by a crash that took its neighbours with it.

    `Exception` and not the guard's own list of types, which is what this was and which defeated the
    point of it. A helper that catches exactly what the code under test catches lets through exactly
    the escape the checks below are looking for, and it took the rest of the file with it.
    """
    try:
        return hookio.payload(stream)
    except Exception as exc:
        return f"it raised {type(exc).__name__}"


class Bare:
    """A stream with a read and no isatty, which is what a wrapper around a pipe can look like."""

    def read(self):
        return '{"a": 1}'


class ReadsNothing:
    """A stream whose `read` answers `None`, which is what a non-blocking stdin with nothing ready
    does."""

    def read(self):
        return None


shut = io.StringIO()
shut.close()

stdin = sys.stdin
sys.stdin = io.StringIO("")
try:
    handed = read_by(io.StringIO('{"a": 1}'))
    empty = read_by(io.StringIO(""))
    bare = read_by(Bare())
    closed = read_by(shut)
    nothing = read_by(ReadsNothing())
    deep = read_by(io.StringIO("[" * 200000 + "]" * 200000))
    # `sys.stdin` itself, because `None` is what CPython puts there when fd 0 is not open and it is
    # the one input that gets through the `isatty` guard and then has no `read` either. Passed as
    # `None` rather than directly, since the argument means "whatever stdin is" and stdin being
    # absent is the case.
    sys.stdin = None
    absent = read_by(None)
finally:
    sys.stdin = stdin

check("a payload is read from the stream it was given", handed, {"a": 1})
# The behaviour the deleted `or "{}"` read as providing, which the ValueError below it already did.
check("and an empty stream is no payload, not a crash", empty, {})
# The two arms of the guard around `isatty`, which nothing reached: narrowing it to
# `except ZeroDivisionError` left the whole suite green. Both arms are real - a stream with no
# `isatty` raises AttributeError, a closed one raises ValueError - and in both cases what a hook may
# not do is propagate it.
check("a stream that has no isatty is read anyway, not refused", bare, {"a": 1})
check("and a closed stream is no payload, rather than an exception", closed, {})
# The gap between those two arms, which they were both wide enough to miss: tolerating a stream that
# cannot answer `isatty` and then reading it regardless only works while everything with no `isatty`
# has a `read`, and `None` has neither.
check("and no stdin at all is no payload either, not an AttributeError", absent, {})
# The two inputs that got through the version of that guard which named its types. Both of them
# reach a hook the ordinary way rather than by contrivance, and neither is an exception type anybody
# would have thought to list: a non-blocking stdin with nothing ready reads as `None`, and enough
# nesting exhausts the stack inside the decoder. Which is why the guard now names none of them.
check("and a stream with nothing ready is no payload, not a TypeError", nothing, {})
check("and a payload too nested to decode is no payload, not a RecursionError", deep, {})

print("a hook may not take a session down with it")

import hook  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp, wire_legacy=False)
    stdin, stdout = sys.stdin, sys.stdout
    captured = io.StringIO()

    def explode(data, root, lines):
        raise RuntimeError("deliberate")

    original = hook.HANDLERS["SessionStart"]
    hook.HANDLERS["SessionStart"] = explode
    try:
        sys.stdin = io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "SessionStart",
                    "session_id": "s",
                    "cwd": str(repo),
                }
            )
        )
        sys.stdout = captured
        code = hook.main("SessionStart")
    finally:
        sys.stdin, sys.stdout = stdin, stdout
        hook.HANDLERS["SessionStart"] = original

    out = json.loads(captured.getvalue())
    context = out["hookSpecificOutput"]["additionalContext"]
    check("an exception is reported, not raised", code, 0)
    check(
        "and it names what broke",
        ("RuntimeError" in context, "deliberate" in context),
        (True, True),
    )
    check("and says the session is unaffected", "Session unaffected" in context, True)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
