#!/usr/bin/env python3
"""Migration step 7, against a synthetic hooks directory and settings files in a temporary root.

What is worth breaking here is what it removes and what it leaves. Unwiring a hook entry that ran
something else as well deletes a command nobody asked to lose. Retiring a script the user's own
settings still name makes every session on the machine start with a failing hook. Editing the
user's settings from one root ends another root's exchange without it knowing. And moving a script
before the wiring to it is gone opens the window the order exists to close. Each is asserted from
both sides: what is left alone, and what next to it has to go.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import decommission
import legacy

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def hook(command):
    return {"type": "command", "command": command}


LEGACY = 'bash "$HOME/.claude/hooks/alpha-session-lane.sh" lane-arg'
OTHER = "bash ~/.claude/hooks/review-requests.sh"


print("unwiring one settings file")

new, removed, problems = decommission.unwired(
    {
        "model": "kept",
        "hooks": {
            "SessionStart": [{"hooks": [hook(LEGACY), hook(OTHER)]}],
            "SessionEnd": [{"matcher": "*", "hooks": [hook(LEGACY)]}],
            "Stop": [],
        },
    }
)
check("the legacy entry is removed and named", (removed, problems), (["alpha-session-lane.sh"], []))
check(
    "a hook beside it in the same group stays",
    new["hooks"].get("SessionStart"),
    [{"hooks": [hook(OTHER)]}],
)
check("an event left with nothing is taken out", "SessionEnd" in new["hooks"], False)
check("one that was empty before is left as it was", new["hooks"].get("Stop"), [])
check("and the rest of the file is untouched", new.get("model"), "kept")

new, removed, _ = decommission.unwired(
    {"hooks": {"SessionEnd": [{"hooks": [hook(LEGACY)]}]}, "model": "kept"}
)
check(
    "a hooks block left empty goes too",
    (new, removed),
    ({"model": "kept"}, ["alpha-session-lane.sh"]),
)

new, removed, _ = decommission.unwired(
    {"hooks": {"SessionEnd": [{"hooks": [hook(LEGACY)]}, {"hooks": [hook(OTHER)]}]}}
)
check(
    "a group left empty goes, and the group beside it stays",
    new["hooks"].get("SessionEnd"),
    [{"hooks": [hook(OTHER)]}],
)

for joined in (f"{LEGACY} && {OTHER}", f"{LEGACY}; {OTHER}", f"{LEGACY} | tee x", f"x=$({LEGACY})"):
    settings = {"hooks": {"SessionStart": [{"hooks": [hook(joined)]}]}}
    new, removed, problems = decommission.unwired(settings)
    # Removing the entry would remove the other command with it.
    check(
        f"a legacy script run among other commands is left for a person ({joined[-12:]!r})",
        (new, removed, len(problems)),
        (settings, [], 1),
    )

for redirected in (f"{LEGACY} 2>&1", f"{LEGACY} &> /dev/null", f"{LEGACY} >&2"):
    new, removed, problems = decommission.unwired(
        {"hooks": {"SessionStart": [{"hooks": [hook(redirected)]}]}}
    )
    # One command with its output redirected, and the most common shape a hook is wired in.
    check(
        f"a redirect is not another command ({redirected[-10:]!r})",
        (removed, problems),
        (["alpha-session-lane.sh"], []),
    )

quiet = {"type": "command", "command": OTHER, "statusMessage": "was alpha-session-lane.sh"}
settings = {"hooks": {"SessionStart": [{"hooks": [quiet, "alpha-session-lane.sh"]}]}}
# Only the command says what an entry runs. Dropping one for a name in its status line deletes a
# hook that never ran the script, and nothing would say so.
try:
    got = decommission.unwired(settings)
except Exception as exc:
    got = f"raised {type(exc).__name__}"
check("a name outside the command does not remove the entry", got, (settings, [], []))

check(
    "a file with no hooks is no edit",
    decommission.unwired({"hooks": "odd"}),
    ({"hooks": "odd"}, [], []),
)

print()
print("planning: under this root edited, machine-wide reported, scripts retired only when unwired")


def guarded(plan, hooks):
    """`apply`, with a raise turned into a failed check rather than the end of the file."""
    try:
        return decommission.apply(plan, hooks, at="t")
    except Exception as exc:
        return [], [f"raised {type(exc).__name__}"]


def layout(tmp):
    tmp = pathlib.Path(tmp).resolve()
    root, home = tmp / "area", tmp / "home"
    hooks = home / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    for name in ("alpha-session-lane.sh", "session_exchange_handoffs.py", "review-requests.sh"):
        (hooks / name).write_text("# script\n")
    local = root / ".claude" / "settings.local.json"
    local.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [hook(LEGACY)]}]}}))
    user = home / ".claude" / "settings.json"
    machine = 'python3 "$HOME/.claude/hooks/session_exchange_handoffs.py"'
    user.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [hook(machine)]}]}}))
    return root, hooks, local, user


with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    before = user.read_text()
    plan = decommission.prepare(root, hooks, user)
    check("no problem", plan.problems, [])
    check(
        "the file under the root is the one edited",
        [(path, names) for path, _, names in plan.edits],
        [(local, ["alpha-session-lane.sh"])],
    )
    check(
        "the user's settings are reported, not edited",
        plan.machine_wide,
        [(user, "session_exchange_handoffs.py")],
    )
    # Retiring a script the user's own settings still name starts every session with a failing hook.
    check(
        "a script wired machine-wide is kept, the rest retired",
        ([p.name for p in plan.retire], [p.name for p in plan.keep]),
        (["alpha-session-lane.sh"], ["session_exchange_handoffs.py"]),
    )
    check("and something that is not legacy is neither", "review-requests.sh" in str(plan), False)
    check("a plan writes nothing", json.loads(local.read_text())["hooks"] != {}, True)

    lines, problems = decommission.apply(plan, hooks, at="20261001T000000Z")
    check("applying makes both changes", (len(lines), problems), (2, []))
    check("the settings under the root no longer wire it", json.loads(local.read_text()), {})
    backup = local.with_name("settings.local.json.bak-20261001T000000Z")
    try:
        kept = json.loads(backup.read_text())
    except (OSError, ValueError) as exc:
        kept = f"raised {type(exc).__name__}"
    check(
        "and the old copy is kept beside it",
        kept,
        {"hooks": {"SessionStart": [{"hooks": [hook(LEGACY)]}]}},
    )
    retired = hooks / "retired-20261001T000000Z"
    check(
        "the script is moved aside, not deleted",
        ((hooks / "alpha-session-lane.sh").exists(), (retired / "alpha-session-lane.sh").is_file()),
        (False, True),
    )
    check(
        "the one still wired machine-wide is where it was",
        (hooks / "session_exchange_handoffs.py").is_file(),
        True,
    )
    check("and the user's settings were never written", user.read_text(), before)
    state = legacy.report(root, hooks, user)
    check(
        "after it the root has no wiring of its own, and the machine-wide half remains",
        (state["scoped"], [n for _, n in state["machine_wide"]]),
        ([], ["session_exchange_handoffs.py"]),
    )
    again = decommission.prepare(root, hooks, user)
    check(
        "a second run has nothing to do", (again.edits, again.retire, again.problems), ([], [], [])
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    stowed = root / "dotfiles" / ".claude" / "settings.json"
    stowed.parent.mkdir(parents=True)
    user.rename(stowed)
    user.symlink_to(stowed)
    plan = decommission.prepare(root, hooks, user)
    # Stowed or symlinked dotfiles under the root are still the user's settings, and still fire for
    # every root on the machine.
    check(
        "the user's settings are machine-wide even when they resolve under the root",
        ([p for p, _, _ in plan.edits], [n for _, n in plan.machine_wide]),
        ([local], ["session_exchange_handoffs.py"]),
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    real = root / "elsewhere.json"
    local.rename(real)
    local.symlink_to(real)
    plan = decommission.prepare(root, hooks, user)
    check(
        "a symlinked settings file is a problem, not replaced by a file",
        [p.split("; ")[-1] for p in plan.problems],
        ["unwire it in the file it points to"],
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    dots = pathlib.Path(tmp).resolve() / "dots" / "settings.local.json"
    dots.parent.mkdir()
    linked = root / "repo" / ".claude" / "settings.local.json"
    linked.parent.mkdir(parents=True)
    dots.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [hook(LEGACY)]}]}}))
    linked.symlink_to(dots)
    plan = decommission.prepare(root, hooks, user)
    # The usual dotfiles shape. It fires for this root, so it is this root's to unwire, and calling
    # it machine-wide would leave the double fire it causes reported as something else.
    check(
        "a file under the root linked to one outside it is this root's, not machine-wide",
        (
            [p.split("; ")[-1] for p in plan.problems],
            [n for _, n in plan.machine_wide],
            [p.name for p in plan.keep],
        ),
        (
            ["unwire it in the file it points to"],
            ["session_exchange_handoffs.py"],
            ["session_exchange_handoffs.py"],
        ),
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    twin = root / "repo" / ".claude" / "settings.local.json"
    twin.parent.mkdir(parents=True)
    twin.symlink_to(local)
    plan = decommission.prepare(root, hooks, user)
    check(
        "a link to a file the run edits anyway is no problem and no second edit",
        (plan.problems, [p for p, _, _ in plan.edits]),
        ([], [local]),
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    plan = decommission.prepare(root, hooks, user)
    backup = local.with_name("settings.local.json.bak-t")
    backup.write_text("theirs")
    (hooks / "retired-t").mkdir()
    free = decommission._free
    # What a run racing this one leaves between the free name being picked and it being taken.
    decommission._free = lambda path: path
    try:
        lines, problems = guarded(plan, hooks)
    finally:
        decommission._free = free
    check("a backup taken in the meantime is never overwritten", backup.read_text(), "theirs")
    check("and the file it was for is left as it was", local.read_text() != "{}\n", True)
    (hooks / "retired-t").rmdir()
    backup.unlink()
    (hooks / "retired-t").mkdir()
    (hooks / "retired-t" / "theirs").write_text("")
    decommission._free = lambda path: path
    try:
        lines, problems = guarded(plan, hooks)
    finally:
        decommission._free = free
    check(
        "a retired directory made in the meantime is not moved into",
        sorted(p.name for p in (hooks / "retired-t").iterdir()),
        ["theirs"],
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    local.chmod(0o640)
    lines, problems = decommission.apply(decommission.prepare(root, hooks, user), hooks, at="t")
    check(
        "a rewritten file keeps its mode",
        (problems, oct(local.stat().st_mode & 0o777)),
        ([], "0o640"),
    )
    local.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [hook(LEGACY)]}]}}))
    (hooks / "alpha-session-lane.sh").write_text("# back again\n")
    lines, problems = decommission.apply(decommission.prepare(root, hooks, user), hooks, at="t")
    check(
        "a second run in the same second overwrites neither the backup nor the retired script",
        (
            problems,
            local.with_name("settings.local.json.bak-t").is_file(),
            local.with_name("settings.local.json.bak-t-2").is_file(),
            (hooks / "retired-t" / "alpha-session-lane.sh").is_file(),
            (hooks / "retired-t-2" / "alpha-session-lane.sh").is_file(),
        ),
        ([], True, True, True, True),
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    user.unlink()
    plan = decommission.prepare(root, hooks, user)
    check(
        "with nothing machine-wide every legacy script is retired",
        sorted(p.name for p in plan.retire),
        ["alpha-session-lane.sh", "session_exchange_handoffs.py"],
    )

print()
print("refusing, and writing nothing when it does")

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    settings = json.loads(local.read_text())
    settings["env"] = {"LANE_HOOK": "~/.claude/hooks/alpha-session-lane.sh"}
    local.write_text(json.dumps(settings))
    plan = decommission.prepare(root, hooks, user)
    check(
        "a legacy name left outside a hook entry is a problem",
        [p.split(" still names ")[-1] for p in plan.problems],
        ["alpha-session-lane.sh outside a hook entry; edit it by hand"],
    )
    text = local.read_text()
    lines, problems = decommission.apply(plan, hooks, at="x")
    check(
        "and applying writes nothing, the script moves included",
        (lines, local.read_text() == text, (hooks / "alpha-session-lane.sh").is_file()),
        ([], True, True),
    )
    check("and says why", problems, ["the plan has problems, so nothing was written"])

    local.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [hook(f"{LEGACY} && x")]}]}}))
    plan = decommission.prepare(root, hooks, user)
    check(
        "a compound command is one problem, not two",
        [p.split(": ", 1)[-1] for p in plan.problems],
        ["a SessionStart hook runs alpha-session-lane.sh among other commands; split it by hand"],
    )
    local.write_text("{")
    plan = decommission.prepare(root, hooks, user)
    check("an unreadable settings file is a problem", len(plan.problems), 1)


print()
print("a run that is cut short")

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    plan = decommission.prepare(root, hooks, user)
    local.unlink()
    lines, problems = guarded(plan, hooks)
    # Retiring the script while the wiring to it may still be there is the window the order closes.
    check(
        "a failed edit stops the scripts from moving",
        (lines, (hooks / "alpha-session-lane.sh").is_file()),
        ([], True),
    )
    check(
        "and says how far it got",
        (len(problems), problems[-1:]),
        (2, ["0 of 2 change(s) made; run it again to finish the rest"]),
    )

with tempfile.TemporaryDirectory() as tmp:
    root, hooks, local, user = layout(tmp)
    plan = decommission.prepare(root, hooks, user)
    (hooks / "alpha-session-lane.sh").unlink()
    lines, problems = guarded(plan, hooks)
    check(
        "a failed move is reported, after the edit it follows",
        (len(lines), problems[-1:]),
        (1, ["1 of 2 change(s) made; run it again to finish the rest"]),
    )

check("a stamp is safe in a directory name", any(c in decommission.stamp() for c in ":-"), False)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
