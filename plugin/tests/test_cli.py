#!/usr/bin/env python3
"""The CLI, run as a real command.

`HOME` is pointed at a tmpdir throughout, which isolates the session registry, the legacy scripts
and the user settings in one move. The registry fixture names this test process as the session's
pid,
because that is how the CLI works out who is calling it: it walks up the process tree until a pid
matches a registry row, since a command run through a tool call has no other way to learn its own
session id and matching on cwd picks the wrong session the moment two of them share a directory.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
CLI = PLUGIN / "lib" / "cli.py"

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def fixture(tmp):
    """A synthetic HOME whose registry knows this test process, and an unmarked area with a repo."""
    tmp = pathlib.Path(tmp).resolve()
    sessions = tmp / "home" / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (tmp / "home" / ".claude" / "hooks").mkdir()
    (sessions / f"{os.getpid()}.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "sessionId": "real-one",
                "name": "the-caller",
                "cwd": str(tmp),
                "status": "busy",
            }
        )
    )
    area = tmp / "area"
    (area / "repo" / ".git").mkdir(parents=True)
    (area / "repo" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (area / "CLAUDE.md").write_text("area\n")
    return tmp / "home", area, area / "repo"


def run(home, cwd, *args):
    done = subprocess.run(
        [sys.executable, str(CLI), "--cwd", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "HOME": str(home)} | {"CC_EXCHANGE_ROOT": ""},
    )
    return done.returncode, done.stdout + done.stderr


print("with no root, every command explains itself rather than guessing")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    code, out = run(home, repo, "show")
    check(
        "show says there is no exchange here",
        (code, "no environment root" in out.lower()),
        (1, True),
    )
    check("and names what init would mark", str(area) in out, True)

print("init")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    code, out = run(home, repo, "init")
    check(
        "marks the area above the repo, not the repo",
        (code, (area / ".claude" / "exchange.json").is_file()),
        (0, True),
    )
    check("and not the repo itself", (repo / ".claude" / "exchange.json").exists(), False)
    check("and creates the store", (area / ".claude" / "exchange" / "handoffs").is_dir(), True)

    code, out = run(home, repo, "init")
    check(
        "running it again reports rather than rewrites", (code, "Already marked" in out), (0, True)
    )

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    # Two sibling areas that are not repos: marking the directory holding them would give each
    # sight of the other's sessions and handoffs, which is the one thing root resolution prevents.
    container = pathlib.Path(tmp) / "container"
    for name in ("one", "two"):
        (container / name).mkdir(parents=True)
        (container / name / "CLAUDE.md").write_text("area\n")
    (container / "CLAUDE.md").write_text("container\n")
    inner = container / "one" / "repo"
    (inner / ".git").mkdir(parents=True)

    code, out = run(home, inner, "init")
    check(
        "defaults to the area rather than the container",
        (code, (container / "one" / ".claude" / "exchange.json").is_file()),
        (0, True),
    )
    code, out = run(home, inner, "init", str(container))
    check(
        "and refuses the container when asked for it by name",
        (code, "Refusing to mark" in out, "separate workspaces" in out),
        (1, True, True),
    )
    check("nothing was written to the container", (container / ".claude").exists(), False)
    code, out = run(home, inner, "init", str(container), "--force")
    check(
        "--force is the only way past it",
        (code, (container / ".claude" / "exchange.json").is_file()),
        (0, True),
    )

print("claim")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")

    code, out = run(
        home, repo, "claim", "--focus", "the hooks manifest", "--path", "a", "--path", "b"
    )
    check("claims as the calling session, by name", (code, "the-caller" in out), (0, True))
    written = json.loads((area / ".claude" / "exchange" / "sessions" / "real-one.json").read_text())
    check(
        "and records what it was told",
        (written["name"], written["focus"], written["paths"], written["git_branch"]),
        ("the-caller", "the hooks manifest", ["a", "b"], "main"),
    )

    code, out = run(home, repo, "claim", "--path", "c")
    written = json.loads((area / ".claude" / "exchange" / "sessions" / "real-one.json").read_text())
    check("a second claim adds rather than replacing", written["paths"], ["a", "b", "c"])

    # Break it: the display name must come from the id being claimed as, not from whoever is
    # calling. Borrowing it labels someone else's claim with this session's name, and then shows
    # everybody a stale row under it.
    code, out = run(home, repo, "claim", "--session", "someone-else", "--focus", "other work")
    other_path = area / ".claude" / "exchange" / "sessions" / "someone-else.json"
    other = json.loads(other_path.read_text())
    check(
        "an explicit session id does not borrow the caller's name",
        ("name" in other, other["focus"]),
        (False, "other work"),
    )

    code, out = run(home, repo, "show")
    check("show lists both claims", (code, "claims    2" in out), (0, True))
    check(
        "with each session's focus",
        ("the hooks manifest" in out, "other work" in out),
        (True, True),
    )
    check(
        "and marks the one with no live session as stale", "no longer in the registry" in out, True
    )

print("doctor")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    code, out = run(home, repo, "doctor")
    check("reports the root and the rule that found it", (code, "by marker" in out), (0, True))
    check("names the first outstanding step", "next      step 4" in out, True)
    # A diagnostic that quietly omits a check reads exactly like one that passed it.
    check("prints the checks it cannot answer rather than skipping them", "[?]" in out, True)
    check("says why each one is unanswerable", "not checkable here" in out, True)
    check("no legacy scripts in this synthetic home", "0 script(s) on disk" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    LEGACY_COMMAND = 'python3 "$HOME/.claude/hooks/session_exchange_handoffs.py"'
    hooks = home / ".claude" / "hooks"
    (hooks / "session_exchange_handoffs.py").write_text("# legacy\n")
    (hooks / "review-requests-check.sh").write_text("# unrelated\n")
    (home / ".claude" / "settings.json").write_text(
        json.dumps(
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
        )
    )

    code, out = run(home, repo, "doctor")
    check("a wired legacy script is a fault, not a note", code, 1)
    check("and is called what it is", "DOUBLE FIRE" in out, True)
    check("the unrelated hook is left out of it", "review-requests" in out, False)
    check("step 7 is outstanding while it is wired", "next      step 4" in out, True)

print("what is not built yet says so, and does not look like a failure")

with tempfile.TemporaryDirectory() as tmp:
    home, area, repo = fixture(tmp)
    run(home, repo, "init")
    for command in ("handoff", "migrate"):
        code, out = run(home, repo, command)
        check(
            f"{command} exits 2 and names the step",
            (code, "step 4" in out, "Nothing was changed" in out),
            (2, True, True),
        )

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
