#!/usr/bin/env python3
"""The scripts this plugin replaces, detected by shape.

`test_hook.py` and `test_cli.py` already drive this module end to end, through a faked `HOME` with
legacy scripts in it and a settings file that wires them. What they assert is the rendered warning,
which is the right thing to assert and is not the same as the module's contract: a sweep of the
table found the rules that only show up when a settings file is unreadable, when a command is
quoted, or when there is no root at all, none of which an end-to-end fixture produces.

The privacy rule is the one to keep in mind while reading: these files hold another environment's
arguments, and a diagnostic has no business quoting them to establish a fact that the basename
already establishes.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import legacy

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def settings(path, command):
    """A settings file wiring one command, in the shape Claude Code actually writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": command}]}]}}
        ),
        encoding="utf-8",
    )


print("a legacy script is recognised by its shape")

for name in (
    "session_exchange_handoffs.py",
    "session-exchange-active-now.sh",
    "alpha-handoff-check.sh",
    "alpha-session-lane.sh",
):
    check(f"{name} is legacy", legacy.looks_legacy(name), True)
# The point of globbing rather than listing: the same script after a rename is still the script,
# and two of the real ones carry a project prefix this plugin must not have a copy of.
check("and so is the same shape renamed", legacy.looks_legacy("session_exchange_anything.py"), True)
for name in ("review-requests.sh", "session_exchange_handoffs.sh", "handoff-check.sh"):
    check(f"{name} is not", legacy.looks_legacy(name), False)

print("what is on disk")

with tempfile.TemporaryDirectory() as tmp:
    hooks = pathlib.Path(tmp) / "hooks"
    hooks.mkdir()
    (hooks / "session_exchange_handoffs.py").write_text("# legacy\n")
    (hooks / "alpha-session-lane.sh").write_text("# legacy\n")
    (hooks / "review-requests.sh").write_text("# unrelated\n")
    # A directory whose name matches. Reported as a script it becomes a fault nobody can clear,
    # because there is no file there to delete.
    (hooks / "session_exchange_old.py").mkdir()

    check(
        "legacy files are found, sorted, and nothing else is",
        [p.name for p in legacy.scripts_on_disk(hooks)],
        ["alpha-session-lane.sh", "session_exchange_handoffs.py"],
    )
    # `iterdir` raises on a directory that is not there, unlike `glob`, so this guard is
    # load-bearing rather than decorative: a machine with no `~/.claude/hooks` is the ordinary case
    # for a fresh install, and a session start is where this runs.
    try:
        missing = legacy.scripts_on_disk(pathlib.Path(tmp) / "never")
    except Exception as exc:
        missing = f"raised {type(exc).__name__}"
    check("a hooks directory that is not there is empty", missing, [])
    try:
        as_string = [p.name for p in legacy.scripts_on_disk(str(hooks))]
    except Exception as exc:
        as_string = f"raised {type(exc).__name__}"
    check(
        "and a directory given as a string reads the same",
        as_string,
        ["alpha-session-lane.sh", "session_exchange_handoffs.py"],
    )

print("which settings files could carry a wiring")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp) / "area"
    user = pathlib.Path(tmp) / "home" / ".claude" / "settings.json"
    settings(user, "true")
    settings(root / ".claude" / "settings.local.json", "true")
    settings(root / "one-repo" / ".claude" / "settings.local.json", "true")
    # Two levels down, and deliberately not found: the wiring being migrated away from is always one
    # level under a root, and walking an area with dozens of repos in it costs a session start real
    # time to find nothing.
    settings(root / "one-repo" / "nested" / ".claude" / "settings.local.json", "true")

    found = legacy.settings_files(root, user)
    check(
        "the user file, the root's own, and each repo one level down",
        [p.relative_to(tmp).as_posix() for p in found],
        [
            "home/.claude/settings.json",
            "area/.claude/settings.local.json",
            "area/one-repo/.claude/settings.local.json",
        ],
    )
    check(
        "a user settings file that does not exist is left out",
        legacy.settings_files(root, pathlib.Path(tmp) / "home" / ".claude" / "nothing.json")[
            0
        ].name,
        "settings.local.json",
    )

print("every string in a settings file is looked at, whatever shape it is in")

check(
    "nested dicts, lists and bare strings all yield",
    sorted(legacy._strings({"a": ["one", {"b": "two"}], "c": "three", "d": 4})),
    ["one", "three", "two"],
)

print("what a wiring reads as")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    # Quoted, with an argument after it, which is how a command with a path in it is really written.
    # Without the quote stripping the whole thing is one token and the basename never matches.
    quoted = root / "quoted" / ".claude" / "settings.local.json"
    settings(quoted, 'python3 "$HOME/.claude/hooks/session_exchange_handoffs.py" --since HEAD~5')
    found, problems = legacy.wirings([quoted])
    check(
        "a quoted command is still split into tokens",
        [name for _, name in found],
        ["session_exchange_handoffs.py"],
    )
    check("and reading it was not a problem", problems, [])
    # The privacy rule. Reporting the token it was found in would put another environment's
    # arguments into a log to establish a fact the basename already establishes.
    check(
        "and nothing reported carries the arguments it sat next to",
        [name for _, name in found if "--since" in name or "$HOME" in name],
        [],
    )

    absent = root / "gone" / ".claude" / "settings.local.json"
    # `settings_files` filters these out, so this only arrives when `wirings` is called directly.
    # Reported as a problem it would be a permanent warning about a file nobody has or wants.
    check("a settings file that is not there is not a problem", legacy.wirings([absent]), ([], []))

    broken = root / "broken" / ".claude" / "settings.local.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{ not json", encoding="utf-8")
    found, problems = legacy.wirings([broken])
    check("a settings file that will not parse finds no wiring", found, [])
    # And says so. Silence here is the failure this module exists to prevent, one step removed: a
    # file that might wire a legacy hook, reported as clean because it could not be read.
    check("but is reported as unknown rather than as clean", len(problems), 1)
    # `problems[0]` bare is an IndexError under the mutation that stops the append, which is the
    # check above failing and then this one crashing instead of failing - the sweep would score that
    # off the traceback rather than off the assertion, and the rest of the file would not run.
    check("and the report names the file", problems and "broken" in problems[0], True)

print("whether a settings file belongs to this root")

with tempfile.TemporaryDirectory() as tmp:
    real = pathlib.Path(tmp).resolve() / "real-area"
    (real / ".claude").mkdir(parents=True)
    link = pathlib.Path(tmp).resolve() / "linked-area"
    link.symlink_to(real)
    outside = pathlib.Path(tmp).resolve() / "elsewhere"
    outside.mkdir()

    inside = real / ".claude" / "x.json"
    check("a file under the root is under it", legacy.under(real, inside), True)
    check("a file beside it is not", legacy.under(real, outside / "x.json"), False)
    # Both directions of the same mistake, one per `resolve` call. The root arrives already resolved
    # and the settings paths are globbed from it, so in the ordinary case the two sides agree; these
    # are the cases where they do not, and an unresolved comparison answers no to both - which files
    # a root's own wiring as machine-wide and then warns about the wrong fault.
    check(
        "a real path is under the symlink that points at its root",
        legacy.under(link, real / ".claude" / "s.json"),
        True,
    )
    check(
        "and a path reached through the symlink is under the real root",
        legacy.under(real, link / ".claude" / "s.json"),
        True,
    )

print("and the report the session start acts on")

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp) / "area"
    root.mkdir()
    hooks = pathlib.Path(tmp) / "hooks"
    hooks.mkdir()
    (hooks / "session_exchange_handoffs.py").write_text("# legacy\n")
    user = pathlib.Path(tmp) / "home" / ".claude" / "settings.json"
    settings(user, "true")

    # On disk and unwired. Inert: it fires nothing, so warning about a doubled injection would be
    # warning about something that cannot happen.
    report = legacy.report(root, hooks_dir=hooks, user_settings=user)
    check(
        "a script on disk is reported",
        [p.name for p in report["on_disk"]],
        ["session_exchange_handoffs.py"],
    )
    check("but on its own it is not a doubled fire", report["double_fire"], False)

    # Where a wiring lives decides which fault it is, and the two are not interchangeable. In the
    # user's own settings it fires for every session on the machine whatever root that session
    # belongs to, so what it injects here is another environment's presence rather than this one's
    # twice. Found on the first real migration, where the machine-wide wiring put another root's
    # rows into a session under this one, and the warning called that a doubled fire.
    settings(user, "python3 $HOME/.claude/hooks/session_exchange_handoffs.py")
    report = legacy.report(root, hooks_dir=hooks, user_settings=user)
    # Asserted as a pair throughout, because `double_fire` alone read True for both cases before the
    # split and would read True for both again if they collapsed back into one.
    check(
        "a wiring in the user's own settings is machine-wide, not this root doubling",
        (report["double_fire"], [name for _, name in report["machine_wide"]]),
        (False, ["session_exchange_handoffs.py"]),
    )
    check(
        "and the wiring names the script",
        [name for _, name in report["wired"]],
        ["session_exchange_handoffs.py"],
    )

    # The other arm: a wiring in a settings file under the root is this root's rendering doubled.
    # With both in place, each is reported as what it is rather than one shadowing the other.
    local = root / ".claude" / "settings.local.json"
    settings(local, "python3 .claude/hooks/session_exchange_handoffs.py")
    report = legacy.report(root, hooks_dir=hooks, user_settings=user)
    check(
        "a wiring under the root doubles this root, while the machine-wide one stays machine-wide",
        (report["double_fire"], [str(path) for path, _ in report["machine_wide"]]),
        (True, [str(user)]),
    )

    # And the root-scoped wiring on its own, which is the state a half-finished step 7 leaves: the
    # machine-wide one gone, this root's still there. Nothing to be machine-wide about, so an empty
    # list rather than a wiring that quietly stayed in the wrong bucket.
    settings(user, "true")
    report = legacy.report(root, hooks_dir=hooks, user_settings=user)
    check(
        "with the machine-wide one gone, only the root's own wiring is left",
        (report["double_fire"], report["machine_wide"], [name for _, name in report["wired"]]),
        (True, [], ["session_exchange_handoffs.py"]),
    )

    # `doctor` run from outside any root, which is the one caller that has no root to search.
    # Without the guard this is `pathlib.Path(None)`, so the command dies instead of reporting what
    # it does know.
    try:
        rootless = legacy.report(None, hooks_dir=hooks, user_settings=user)
    except Exception as exc:
        rootless = f"raised {type(exc).__name__}"
    check(
        "no root still reports what is on disk, rather than raising",
        rootless
        if isinstance(rootless, str)
        else (rootless["wired"], [p.name for p in rootless["on_disk"]]),
        ([], ["session_exchange_handoffs.py"]),
    )

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
