"""Detect the scripts this plugin replaces, on disk and still wired.

Half-migrated is both the most likely state and the most dangerous one. If the plugin installs
while a legacy hook is still wired, both fire: two presence renderers over the same source and a
doubled SessionStart injection. And because the legacy pair exits 0 when it matches nothing,
half-migrated and finished look identical at the output. That is the failure class this whole
rebuild exists to delete, so the migration is not allowed to reintroduce it.

Which is why this is a startup guard and not just something `doctor` asks about. If SessionStart
sees a legacy script still wired it says so, every session, until it is gone. A stalled migration
sitting unnoticed is exactly how the parser bug lasted ten days.

**Detection is by shape, never by literal name.** Two of the scripts carry one environment's project
prefix, and a generalised tool must not ship another workspace's project name inside it. Matching
the shape also picks up the same scripts after a rename, which a literal never would.
"""

from __future__ import annotations

import fnmatch
import json
import pathlib

LEGACY_GLOBS = (
    "session_exchange_*.py",
    "session-exchange-*.sh",
    "*-handoff-check.sh",
    "*-session-lane.sh",
)

HOOKS_DIR = pathlib.Path.home() / ".claude" / "hooks"
USER_SETTINGS = pathlib.Path.home() / ".claude" / "settings.json"


def looks_legacy(name):
    return any(fnmatch.fnmatch(name, pattern) for pattern in LEGACY_GLOBS)


def names_in(text):
    """The legacy scripts one string mentions, by bare name. Step 7 removes by the same rule."""
    names = set()
    for token in text.replace('"', " ").replace("'", " ").split():
        name = pathlib.PurePath(token).name
        if looks_legacy(name):
            names.add(name)
    return names


def scripts_on_disk(hooks_dir=HOOKS_DIR):
    """Legacy scripts present in the hooks directory, sorted.

    Deliberately not a check for the plugin's own handlers: those live under the plugin root and are
    named for their event, so no glob here can reach them.
    """
    hooks_dir = pathlib.Path(hooks_dir)
    if not hooks_dir.is_dir():
        return []
    return sorted(p for p in hooks_dir.iterdir() if p.is_file() and looks_legacy(p.name))


def settings_files(root, user_settings=USER_SETTINGS):
    """Every settings file that could carry a hook wiring for this root.

    Bounded on purpose. The per-repo wiring being migrated away from lives in gitignored
    `settings.local.json` files one directory down from a root, so that is the depth searched; a
    recursive walk of an area with dozens of repos in it would cost a session start real time to
    find nothing.
    """
    root = pathlib.Path(root)
    found = [user_settings] if user_settings and pathlib.Path(user_settings).is_file() else []
    for candidate in [
        root / ".claude" / "settings.local.json",
        *sorted(root.glob("*/.claude/settings.local.json")),
    ]:
        if candidate.is_file():
            found.append(candidate)
    return found


def _strings(obj):
    """Every string anywhere in a parsed settings file.

    A recursive walk rather than a read of the documented hook structure, because a wiring that is
    in an undocumented or a future shape still fires, and a guard that only looks where it expects
    to find something is not a guard.
    """
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)


def wirings(settings_paths):
    """`(settings_path, script_name)` for each legacy script referenced. Plus read problems.

    Returns `(found, problems)`. Only the settings file and the script's bare name are reported,
    never the command string: these files hold another environment's arguments, and a diagnostic has
    no business quoting them to establish a fact that the basename already establishes.
    """
    found, problems = [], []
    for path in settings_paths:
        path = pathlib.Path(path)
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            problems.append(f"{path} could not be read, so wiring there is unknown: {exc}")
            continue
        names = set()
        for text in _strings(settings):
            names |= names_in(text)
        found += [(path, name) for name in sorted(names)]
    return found, problems


def report(root, hooks_dir=HOOKS_DIR, user_settings=USER_SETTINGS):
    """Everything known about the legacy half, from live state only.

    No recorded claim of progress anywhere: a migration that reports where it thinks it got to is a
    migration that can be wrong about it.
    """
    on_disk = scripts_on_disk(hooks_dir)
    wired, problems = wirings(settings_files(root, user_settings)) if root else ([], [])
    # Where a wiring lives decides what it does wrong, and the two are not the same fault. One in a
    # settings file under this root fires for this root and doubles its rendering. One in the user's
    # own settings fires for every session on the machine whatever root it belongs to, so what it
    # injects here is some other environment's presence - the failure root resolution exists to
    # prevent, arriving through the legacy half. Observed that way round on the first real
    # migration rather than guessed: the machine-wide wiring rendered another root's rows into a
    # session under this one.
    #
    # Every other file searched was found under this root, so the user's settings are the only
    # machine-wide one, by the path they were searched at. Not by where they resolve: stowed into a
    # tree under this root they are still the user's, and a `settings.local.json` linked to a
    # checkout elsewhere still fires for this root.
    user = pathlib.Path(user_settings) if user_settings else None
    scoped = [(path, name) for path, name in wired if pathlib.Path(path) != user]
    return {
        "on_disk": on_disk,
        "wired": wired,
        "problems": problems,
        # The condition worth a warning is a wiring, not a file. An unwired script on disk is
        # inert; a wired one fires alongside the plugin and doubles the injection.
        "double_fire": bool(scoped),
        # Both halves named, rather than one and "the rest": each warning names the scripts that
        # belong to its own fault, so neither sends a reader to a settings file that does not
        # mention them.
        "scoped": scoped,
        "machine_wide": [pair for pair in wired if pair not in scoped],
    }
