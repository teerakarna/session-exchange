#!/usr/bin/env python3
"""The two shell handlers, run the way Claude Code runs them.

Everything else in here reaches `lib/hook.py` directly, which means the wiring between the two has
never been exercised by anything: `hooks/hooks.json` names a shell script, the script finds the
plugin root and an interpreter, and only then does the Python start. Three chances to be broken in a
way that looks exactly like a machine where nothing needed doing, and a session start is the one
place a silent failure is invisible by construction - nobody notices context that was not injected.

So this is the smoke test, and it asserts the handler's own rules rather than the module's:

- the real path works end to end, from a payload on stdin to a claim on disk
- `CLAUDE_PLUGIN_ROOT` is used when Claude Code sets it, and derived from the script's location when
  it does not, which is the case for anyone running the handler by hand
- no `python3` on PATH is said out loud on start, because a plugin that is installed and inert is
  otherwise indistinguishable from one with nothing to do
- a Python side that exits non-zero still leaves the handler at 0. Rule 2 of this plugin is that a
  hook never fails a session, and `set -e` is deliberately absent for it.

Bash rather than `sh`: the scripts declare `#!/usr/bin/env bash` and use `BASH_SOURCE`, so running
them under anything else would be testing a different program.

Outside the sweep's reach, and worth saying so here because nothing else will: `mutate.py` patches
Python modules under `plugin/lib`, so no table can assert that these checks still bite. Every rule
below was probed by hand instead, by breaking the handler eight ways and recording which check named
it. That record is in the PR that added this file, which is the only place it exists.
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


def fire(script, payload, home, *, cwd, env=None, plugin_root=PLUGIN):
    """Run a handler the way the wiring does. Returns `(exit code, stdout)`.

    `CLAUDE_PLUGIN_ROOT` is passed explicitly because Claude Code sets it; the one check below that
    is about the fallback passes `plugin_root=None` to leave it unset.
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
    return done.returncode, done.stdout


print("session start, through the handler rather than the module")

with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    code, out = fire(
        "session-start.sh",
        {"hook_event_name": "SessionStart", "session_id": "sess-1", "cwd": str(repo)},
        home,
        cwd=repo,
    )
    check("exits 0", code, 0)
    # Silent, because there is nothing wrong and nothing to render yet. The claim is the evidence
    # that the whole chain ran: the script found the root, found an interpreter, and the Python side
    # wrote a file under the marked directory rather than under the repo.
    check("says nothing when there is nothing to say", out, "")
    check(
        "and seeded the claim under the root, which is the whole chain having run",
        (root / ".claude" / "exchange" / "sessions" / "sess-1.json").is_file(),
        True,
    )

    print("session end, through the handler")

    code, out = fire(
        "session-end.sh",
        {"hook_event_name": "SessionEnd", "session_id": "sess-1", "cwd": str(repo)},
        home,
        cwd=repo,
    )
    check("exits 0 and stays silent", (code, out), (0, ""))
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
    code, out = fire(
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

print("finding the plugin without being told where it is")

# `CLAUDE_PLUGIN_ROOT` is set by Claude Code and by nothing else, so the fallback is the path taken
# by anyone running a handler by hand to see what it does - which is the first thing a contributor
# does and the first thing a bug report asks for. Run from somewhere else entirely, so a fallback
# that resolved to the working directory rather than to the script's own would fail here.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    code, out = fire(
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
# breaking the machine. `command -v` and `echo` are bash builtins, so the script still runs.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    empty = pathlib.Path(tmp) / "empty-path"
    empty.mkdir()
    code, out = fire(
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
    check("and wrote nothing", (root / ".claude" / "exchange").exists(), False)

# The asymmetry is deliberate and worth pinning: nothing reads injected context at session end, so
# the end handler has nobody to tell and says nothing. Asserted rather than left implicit, because
# the obvious "fix" is to make the two handlers match.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    empty = pathlib.Path(tmp) / "empty-path"
    empty.mkdir()
    code, out = fire(
        "session-end.sh",
        {"hook_event_name": "SessionEnd", "session_id": "s", "cwd": str(repo)},
        home,
        cwd=repo,
        env={"PATH": str(empty)},
    )
    check("session end with no interpreter is silent, not noisy", (code, out), (0, ""))

print("a Python side that fails")

# Rule 2: a hook never fails a session. `set -e` is deliberately absent and every path out of the
# script is an explicit `exit 0`, and until here nothing asserted either - the module catches its
# own exceptions, so no real payload can make `hook.py` exit non-zero and the `|| exit 0` was
# unreachable from any input. A stand-in plugin root is the seam that reaches it.
with tempfile.TemporaryDirectory() as tmp:
    home, root, repo = fixture(tmp)
    fake = pathlib.Path(tmp) / "fake-plugin"
    (fake / "lib").mkdir(parents=True)
    (fake / "lib" / "hook.py").write_text("import sys\nsys.exit(3)\n")
    for script, label in (("session-start.sh", "start"), ("session-end.sh", "end")):
        code, out = fire(
            script,
            {"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
            home,
            cwd=repo,
            plugin_root=fake,
        )
        check(f"a Python side exiting 3 still leaves {label} at 0", (code, out), (0, ""))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nall checks passed")
