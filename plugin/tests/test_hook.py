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


def fixture(tmp, *, wire_legacy):
    """A synthetic HOME, a marked root, and a repo inside it."""
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

    wiring = (
        {
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
        if wire_legacy
        else {"hooks": {}}
    )
    (home / ".claude" / "settings.json").write_text(json.dumps(wiring))

    root = tmp / "area"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "exchange.json").write_text(json.dumps({"name": "area"}))
    repo = root / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return home, root, repo


def run(event, payload, home, env=None):
    """Fire the hook. Returns `(exit code, injected context or None)`."""
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    environ.update(env or {})
    done = subprocess.run(
        [sys.executable, str(LIB / "hook.py"), event],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=environ,
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
    check("warns that legacy hooks are still wired", "still wired" in context, True)
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
# The read end is closed before the process starts, so the write is broken from its first byte and
# there is no race to lose.


def run_into_a_dead_pipe(event, payload, home):
    """Fire the hook with stdout a pipe nobody is reading. Returns `(exit code, stderr)`."""
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        done = subprocess.run(
            [sys.executable, str(LIB / "hook.py"), event],
            input=json.dumps(payload),
            stdout=write_fd,
            stderr=subprocess.PIPE,
            text=True,
            env=environ,
            timeout=30,
        )
    finally:
        os.close(write_fd)
    return done.returncode, done.stderr


with tempfile.TemporaryDirectory() as tmp:
    # Legacy wiring, so there is a line to inject. With nothing to say `emit` returns before it
    # writes, and the check would pass on any version of this module.
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
    )
    check("a hook whose reader has closed stdout still exits 0", code, 0)
    # Both halves. The exit status is what Claude Code acts on, and 120 is what a failed shutdown
    # flush produces, but a version that exits 0 while still printing a traceback has moved the
    # problem rather than fixed it.
    check("and leaves nothing on stderr", err, "")

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
