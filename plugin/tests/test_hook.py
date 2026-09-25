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
