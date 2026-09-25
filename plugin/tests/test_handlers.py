#!/usr/bin/env python3
"""The two shell handlers, run the way Claude Code runs them.

Everything else in here reaches `lib/hook.py` directly, which means the wiring between the two has
never been exercised by anything: `hooks/hooks.json` names a shell script, the script finds the
plugin root and an interpreter, and only then does the Python start. Three chances to be broken in a
way that looks exactly like a machine where nothing needed doing, and a session start is the one
place a silent failure is invisible by construction - nobody notices context that was not injected.

So this is the smoke test, and it asserts the handler's own rules rather than the module's:

- the real path works end to end, from a payload on stdin to a claim on disk
- `CLAUDE_PLUGIN_ROOT` is used when Claude Code sets it, and derived from the script's location
  when it does not, which is the case for anyone running the handler by hand. Both directions,
  and with inputs that disagree: the variable pointed at this plugin's own directory is what the
  fallback derives anyway, so that pair of cases cannot say which one was read
- no `python3` on PATH is said out loud on start, because a plugin that is installed and inert is
  otherwise indistinguishable from one with nothing to do
- a Python side that exits non-zero still leaves the handler at 0. Rule 2 of this plugin is that a
  hook never fails a session, and `set -e` is deliberately absent for it.

Bash rather than `sh`: the scripts declare `#!/usr/bin/env bash` and use `BASH_SOURCE`, so running
them under anything else would be testing a different program.

Outside the sweep's reach, and worth saying so here because nothing else will: `mutate.py` patches
Python modules under `plugin/lib`, so no table can assert that these checks still bite. Every rule
below was probed by hand instead, by breaking the handler fourteen ways and recording which check
named it. That record is in the PR that added this file, which is the only place it exists.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parent
HANDLERS = PLUGIN / "hooks-handlers"
# Resolved once, absolutely, because one check below runs a handler with PATH emptied and a bare
# `bash` in the argv would be looked up in that same empty PATH - so the case about the script's own
# guard would fail before the script started, on a FileNotFoundError naming the shell.
BASH = shutil.which("bash") or "/bin/bash"

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def fixture(tmp):
    """A synthetic HOME and a marked root with a repo inside it.

    Smaller than `test_hook.py`'s: nothing here is about legacy wiring or the registry, and an
    absent `~/.claude` is a case the modules already handle, so the only thing HOME has to be is
    somewhere other than this machine's.
    """
    tmp = pathlib.Path(tmp).resolve()
    home = tmp / "home"
    home.mkdir()
    root = tmp / "area"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "exchange.json").write_text(json.dumps({"name": "area"}))
    repo = root / "repo"
    repo.mkdir()
    return home, root, repo


def standin(where, body):
    """A plugin tree that is not this one, with a `lib/hook.py` that does as it is told.

    Two of the handler's rules need a Python side under the test's control rather than the real one.
    Whether `CLAUDE_PLUGIN_ROOT` is read at all cannot be shown by passing this plugin's own
    directory, since that is what the fallback derives anyway. And `|| exit 0` is unreachable from
    any payload, because `hook.py` catches its own exceptions, so the only way to make the Python
    side fail is to hand the handler a Python side that fails.
    """
    (where / "lib").mkdir(parents=True)
    (where / "lib" / "hook.py").write_text(body)
    return where


def fire(script, payload, home, *, cwd, env=None, plugin_root=PLUGIN):
    """Run a handler the way the wiring does. Returns `(exit code, stdout, stderr)`.

    `CLAUDE_PLUGIN_ROOT` is passed explicitly because Claude Code sets it; the checks below that are
    about the fallback pass `plugin_root=None` to leave it unset.

    stderr is returned rather than discarded because two of these handlers' rules are only visible
    there. Nothing reads it, which is exactly why a line arriving on it is a defect: it means the
    script ran something it thought it had already checked for, and no other assertion can see that.
    """
    environ = dict(os.environ, HOME=str(home))
    environ.pop("CC_EXCHANGE_ROOT", None)
    if plugin_root is None:
        environ.pop("CLAUDE_PLUGIN_ROOT", None)
    else:
        environ["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    environ.update(env or {})
    done = subprocess.run(
        [BASH, str(HANDLERS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=environ,
        cwd=str(cwd),
        timeout=60,
    )
    return done.returncode, done.stdout, done.stderr


print("session start, through the handler rather than the module")

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    code, out, err = fire(
        "session-start.sh",
        {"hook_event_name": "SessionStart", "session_id": "sess-1", "cwd": str(repo)},
        home,
        cwd=repo,
    )
    check("exits 0", code, 0)
    # Silent on both streams, because there is nothing wrong and nothing to render yet. The claim is
    # the evidence that the whole chain ran: the script found the root, found an interpreter,
    # and the Python side wrote a file under the marked directory rather than under the repo.
    check("says nothing when there is nothing to say", (out, err), ("", ""))
    check(
        "and seeded the claim under the root, which is the whole chain having run",
        (root / ".claude" / "exchange" / "sessions" / "sess-1.json").is_file(),
        True,
    )

    print("session end, through the handler")

    code, out, err = fire(
        "session-end.sh",
        {"hook_event_name": "SessionEnd", "session_id": "sess-1", "cwd": str(repo)},
        home,
        cwd=repo,
    )
    check("exits 0 and stays silent", (code, out, err), (0, "", ""))
    check(
        "and the claim is gone",
        (root / ".claude" / "exchange" / "sessions" / "sess-1.json").exists(),
        False,
    )

print("what it injects when something is wrong")

# Through the handler rather than the module, because stdout is the interface here: the script runs
# `python3 lib/hook.py` and passes whatever it prints straight through, and a redirect or a `>&2`
# anywhere in that chain would make every injected line vanish while every check above stayed green.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    code, out, err = fire(
        "session-start.sh",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
        cwd=repo,
        env={"CC_EXCHANGE_ROOT": str(pathlib.Path(tmp) / "nowhere")},
    )
    parsed = json.loads(out) if out.strip() else None
    context = (parsed or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    check("still exits 0", code, 0)
    check("and what reaches stdout is the JSON Claude Code reads", bool(parsed), True)
    check("with the problem in it", "CC_EXCHANGE_ROOT" in context, True)
    check("and nothing on stderr, which nobody would have read", err, "")

print("finding the plugin, told and not told where it is")

# Two directions, and the trap is that the obvious inputs for them agree. `CLAUDE_PLUGIN_ROOT`
# set to this plugin's own directory is byte for byte what the fallback derives, because these
# checks run the real script by absolute path - so a handler that had stopped reading the
# variable at all would pass that case, and every check above it. Two inputs that agree cannot
# say which one was read.
#
# So the variable is pointed at a tree that is not this one, and the marker it prints is the proof.
# In production that is the only thing keeping the handler honest: `hooks.json` runs the script as
# "${CLAUDE_PLUGIN_ROOT}/hooks-handlers/session-start.sh", and once installed the tree it sits in is
# reached through a path the script cannot assume anything about.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    marked = standin(pathlib.Path(tmp) / "elsewhere", 'print("ran out of the marked tree")\n')
    code, out, err = fire(
        "session-start.sh",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
        cwd=repo,
        plugin_root=marked,
    )
    check(
        "CLAUDE_PLUGIN_ROOT is the tree that gets run, not the one the script sits in",
        (code, out.strip()),
        (0, "ran out of the marked tree"),
    )

# The other direction. The fallback is the path taken by anyone running a handler by hand to see
# what it does, which is the first thing a contributor does and the first thing a bug report asks
# for. Run from somewhere else entirely, so a fallback resolving to the working directory rather
# than to the script's own location would fail here.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    code, out, err = fire(
        "session-start.sh",
        {"hook_event_name": "SessionStart", "session_id": "sess-2", "cwd": str(repo)},
        home,
        cwd=pathlib.Path(tmp),
        plugin_root=None,
    )
    check(
        "an unset CLAUDE_PLUGIN_ROOT is derived from where the script is",
        (code, (root / ".claude" / "exchange" / "sessions" / "sess-2.json").is_file()),
        (0, True),
    )

print("no python3 on PATH")

# PATH emptied rather than python3 removed, which is the difference between testing the guard and
# breaking the machine. `command -v`, `echo`, `cd` and `pwd` are bash builtins, so the guard itself
# still runs with nothing on PATH at all.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    empty = pathlib.Path(tmp) / "empty-path"
    empty.mkdir()
    code, out, err = fire(
        "session-start.sh",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
        cwd=repo,
        env={"PATH": str(empty)},
    )
    check("exits 0 rather than failing the session", code, 0)
    # The one thing this plugin says out loud on plain stdout rather than as a JSON reply, because
    # there is no interpreter left to build one with. Installed and inert has to be distinguishable
    # from installed and idle, and this line is the only thing that distinguishes them.
    check("but says why it is doing nothing", "python3 is not on PATH" in out, True)
    check("and marks the line as coming from this plugin", "[session-exchange]" in out, True)

# `dirname` is the one thing in either script that is not a builtin, so this is the combination
# where the fallback cannot be computed: no PATH, and nothing telling the script where it lives.
# It still has to reach the guard and say its line, which it does, at the cost of one `command
# not found` on a stream nobody reads. That cost is why this asserts stdout and the code only.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    empty = pathlib.Path(tmp) / "empty-path"
    empty.mkdir()
    code, out, err = fire(
        "session-start.sh",
        {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
        home,
        cwd=repo,
        env={"PATH": str(empty)},
        plugin_root=None,
    )
    check(
        "an unresolvable plugin root still reaches the guard and says so",
        (code, "python3 is not on PATH" in out),
        (0, True),
    )

# The asymmetry is deliberate and worth pinning: nothing reads injected context at session end, so
# the end handler has nobody to tell and says nothing. Asserted rather than left implicit, because
# the obvious "fix" is to make the two handlers match.
#
# stderr is in the assertion because stdout alone cannot see this guard at all. Delete the
# `command -v` line from session-end.sh and bash's own "command not found" goes to stderr while
# `|| exit 0` swallows the 127, so stdout stays empty and the exit code stays 0. On a machine
# with no python3 that is a line at the end of every session, forever, with nothing objecting.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    empty = pathlib.Path(tmp) / "empty-path"
    empty.mkdir()
    code, out, err = fire(
        "session-end.sh",
        {"hook_event_name": "SessionEnd", "session_id": "s", "cwd": str(repo)},
        home,
        cwd=repo,
        env={"PATH": str(empty)},
    )
    check("session end with no interpreter is silent, not noisy", (code, out, err), (0, "", ""))

print("a Python side that fails")

# Rule 2: a hook never fails a session. `set -e` is deliberately absent and every path out of the
# script is an explicit `exit 0`, and until here nothing asserted either - the module catches its
# own exceptions, so no real payload can make `hook.py` exit non-zero and the `|| exit 0` was
# unreachable from any input. A stand-in plugin root is the seam that reaches it.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    fake = standin(pathlib.Path(tmp) / "fake-plugin", "import sys\nsys.exit(3)\n")
    for script, event in (("session-start.sh", "SessionStart"), ("session-end.sh", "SessionEnd")):
        code, out, err = fire(
            script,
            {"hook_event_name": event, "session_id": "s", "cwd": str(repo)},
            home,
            cwd=repo,
            plugin_root=fake,
        )
        label = event.replace("Session", "").lower()
        check(f"a Python side exiting 3 still leaves {label} at 0", (code, out), (0, ""))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nall checks passed")
