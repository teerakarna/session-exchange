"""Migration step 7: unwiring the legacy hooks under this root, and retiring their scripts.

`legacy.py` finds the legacy half. This module is the part that removes it, and it removes less
than it can see, on purpose.

**Only wiring under this root is edited.** A legacy hook wired in the user's own settings fires for
every root on the machine, and another root may still be running on it: unwiring it from here would
end that root's exchange in silence, from a session that cannot see it. And that file is often
generated rather than written - layered, merged, templated - so an edit to the live copy is undone
by the next run of whatever generates it, which would report a step done that comes back. So it is
reported, by file and script name, and left for whoever owns it.

**Scripts are retired, not deleted, and only once nothing visible wires them.** A script the user's
settings still name stays where it is, or every session on the machine starts with a failing hook.
The rest move into a dated `retired-` directory beside them. A root this one cannot see may still
wire one, and its next session then fails loudly on the missing file rather than quietly, which is
the failure the other way round from the one this project started from; moving the file back undoes
it.

**Unwire first, then retire.** The other order leaves a window in which a wired hook points at a
file that is gone.

**A plan first, and nothing written while it has a problem**, the same rule as step 4. A hook entry
that runs a legacy script among other commands is a problem rather than a removal, since removing
the entry would remove the other commands with it, and so is a legacy name left anywhere in a file
after its hook entries are gone. The run also refuses until step 4 is finished and this root is
marked: unwiring the ledger's hooks before its open handoffs are in the store loses the only thing
that was surfacing them.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import shutil
import sys
from typing import Any, NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import legacy
import store

# A hook command with any of these in it runs more than one thing, and only a person can say which
# part to keep. Redirects are taken out first, since `2>&1` and `&>` run one thing.
COMPOUND = re.compile(r"[;&|\n`]|\$\(")
REDIRECT = re.compile(r"\d*>&\d*|&>")


class Prepared(NamedTuple):
    """What a run would do, with nothing done.

    `edits` is one `(settings_path, new_settings, names_removed)` per file under the root. `retire`
    are the scripts to move and `keep` the ones still wired machine-wide, each paired with the
    settings files that wire it.
    """

    edits: list[tuple[pathlib.Path, dict[str, Any], list[str]]]
    machine_wide: list[tuple[pathlib.Path, str]]
    retire: list[pathlib.Path]
    keep: list[pathlib.Path]
    problems: list[str]


def unwired(settings):
    """`(new_settings, names_removed, problems)`, with every legacy hook entry taken out.

    An event or matcher group left with no hooks is taken out with it, since an empty one is clutter
    nobody wrote. One that was empty before is left alone, since somebody did.
    """
    new = copy.deepcopy(settings)
    removed, problems = set(), []
    events = new.get("hooks") if isinstance(new, dict) else None
    if not isinstance(events, dict):
        return new, [], []
    for event in list(events):
        groups = events[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                kept_groups.append(group)
                continue
            kept = []
            for hook in inner:
                # The command only. A name in any other field is no reason to drop the entry, and
                # one left there is caught afterwards as a name still in the file.
                command = hook.get("command") if isinstance(hook, dict) else None
                names = legacy.names_in(command) if isinstance(command, str) else set()
                if not names:
                    kept.append(hook)
                elif COMPOUND.search(REDIRECT.sub(" ", command)):
                    kept.append(hook)
                    problems.append(
                        f"a {event} hook runs {', '.join(sorted(names))} among other commands;"
                        " split it by hand"
                    )
                else:
                    removed |= names
            if kept or not inner:
                kept_groups.append(dict(group, hooks=kept))
        if kept_groups or not groups:
            events[event] = kept_groups
        else:
            del events[event]
    if not events and settings.get("hooks"):
        del new["hooks"]
    return new, sorted(removed), problems


def prepare(root, hooks_dir=legacy.HOOKS_DIR, user_settings=legacy.USER_SETTINGS):
    """Read the settings and the hooks directory and decide everything. Writes nothing."""
    state = legacy.report(root, hooks_dir, user_settings)
    problems = list(state["problems"])
    edits = []
    for path in sorted({path for path, _ in state["scoped"]}):
        # Replacing a link with a file would detach it from whatever it pointed into.
        if path.is_symlink():
            problems.append(f"{path} is a symlink; unwire it in the file it points to")
            continue
        try:
            settings = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{path} could not be read: {type(exc).__name__}")
            continue
        new, removed, faults = unwired(settings)
        problems += [f"{path}: {fault}" for fault in faults]
        left = set().union(*(legacy.names_in(text) for text in legacy._strings(new)))
        if left and not faults:
            problems.append(
                f"{path} still names {', '.join(sorted(left))} outside a hook entry;"
                " edit it by hand"
            )
        if removed:
            edits.append((path, new, removed))
    held = {name for _, name in state["machine_wide"]}
    retire = [path for path in state["on_disk"] if path.name not in held]
    keep = [path for path in state["on_disk"] if path.name in held]
    return Prepared(edits, state["machine_wide"], retire, keep, problems)


def stamp():
    """A directory-safe form of `store.now`."""
    return store.now().replace("-", "").replace(":", "")


def _free(path):
    """`path`, or the first free `path-N`, so a second run never overwrites the first."""
    candidate, n = path, 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}-{n}")
    return candidate


def _rewrite(path, obj):
    """Atomically replace `path` with `obj`, keeping its mode. Returns a problem or None.

    Not `store.write_json`, whose temp file takes the default mode: these files can hold tokens,
    and one that was 0600 has to stay 0600 for the whole of the write, not after it.
    """
    tmp = path.with_name(f"{store.TMP_PREFIX}{os.getpid()}-{path.name}")
    try:
        mode = path.stat().st_mode & 0o777
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return f"could not write {path}: {exc}"
    return None


def apply(prepared, hooks_dir=legacy.HOOKS_DIR, at=None):
    """Write the plan. Returns `(lines, problems)`. Refuses outright on a plan with problems."""
    if prepared.problems:
        return [], ["the plan has problems, so nothing was written"]
    at = at or stamp()
    lines, problems = [], []
    for path, new, removed in prepared.edits:
        backup = _free(path.with_name(f"{path.name}.bak-{at}"))
        try:
            shutil.copy2(path, backup)
        except OSError as exc:
            problems.append(f"could not back up {path}, so it was left as it was: {exc}")
            continue
        problem = _rewrite(path, new)
        if problem:
            problems.append(problem)
        else:
            lines.append(f"unwired   {', '.join(removed)} in {path}; the old copy is {backup.name}")
    # Retiring a script that a failed edit above still wires is the window this order exists to
    # close, so a failed edit stops the moves.
    if not problems and prepared.retire:
        retired = _free(pathlib.Path(hooks_dir) / f"retired-{at}")
        try:
            retired.mkdir()
        except OSError as exc:
            problems.append(f"could not make {retired}: {exc}")
        for script in prepared.retire if retired.is_dir() else []:
            try:
                script.rename(retired / script.name)
            except OSError as exc:
                problems.append(f"could not move {script.name}: {exc}")
            else:
                lines.append(f"retired   {script.name} to {retired.name}/")
    if problems:
        total = len(prepared.edits) + len(prepared.retire)
        problems.append(f"{len(lines)} of {total} change(s) made; run it again to finish the rest")
    return lines, problems
