"""A session's stated intent: seed it, update it, clear it.

Claims exist because the native registry cannot answer the question that matters. The registry
knows a session is alive and whether it is mid-turn; `status: idle` there means "not currently in a
turn", not "finished". So presence rendered from the registry alone can say who is running and
never what they are doing, and "set your row to idle when you are done" stops depending on a
session remembering to.

Claims inform and never block. Every collision on record was someone not reading, and a lock on a
path would be a new failure mode bought with no measured benefit.
"""

from __future__ import annotations

import pathlib

import store
import validate

SCHEMA = validate.load("claim")

LIST_FIELDS = ("repos", "paths", "tickets")


def path(root, session_id):
    return store.sessions_dir(root) / f"{session_id}.json"


def git_branch(cwd):
    """The branch name from `.git/HEAD`, or None.

    Read rather than shelled out: a hook runs on every session start, and `git` is both slower and
    one more thing that can be missing. Detached HEAD holds a bare sha, which is not a branch, so it
    reads as None rather than as a 40-character branch name.

    `UnicodeDecodeError` is next to `OSError` because it is the same shape of failure and was not
    covered: a real HEAD is ASCII, but a truncated or corrupt one holds whatever is on disk, and
    decoding is not an `OSError`. This runs inside `seed`, so an exception here is not a missing
    branch, it is a session with no claim at all and no presence for anyone else to read.
    """
    for candidate in (pathlib.Path(cwd), *pathlib.Path(cwd).parents):
        head = candidate / ".git" / "HEAD"
        if not head.is_file():
            continue
        try:
            text = head.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return text[len("ref: refs/heads/") :] if text.startswith("ref: refs/heads/") else None
    return None


def seed(root, session_id, cwd, name=None):
    """Create a claim from what the hook payload already knows.

    Keeps an existing `focus`, `repos`, `paths` and `tickets` if there is one: SessionStart fires on
    resume and on compact as well as on startup, and wiping what the session said about itself
    because its context was compacted would be a regression the session cannot see.

    Returns `(claim, problem)`.
    """
    session_id = store.safe_id(session_id)
    if session_id is None:
        return None, "session id is missing or not usable as a filename; claim not written"

    existing, problem = store.read_json(path(root, session_id), SCHEMA)
    claim = dict(existing) if existing else {}
    claim.update(session_id=session_id, cwd=str(cwd), updated_at=store.now())
    if name:
        claim["name"] = name
    branch = git_branch(cwd)
    if branch:
        claim["git_branch"] = branch
    elif "git_branch" in claim:
        del claim["git_branch"]

    write_problem = store.write_json(path(root, session_id), claim, SCHEMA)
    return (None, write_problem) if write_problem else (claim, problem)


def update(root, session_id, focus=None, add=None, replace=None, clear_fields=()):
    """Change what a session says about itself. Returns `(claim, problem)`.

    `add` and `replace` both map a list field to values; adding is the default because a session
    picking up a second repo mid-task is the common case and having to restate the first one is how
    a claim goes stale.
    """
    session_id = store.safe_id(session_id)
    if session_id is None:
        return None, "session id is not usable as a filename"

    claim, problem = store.read_json(path(root, session_id), SCHEMA)
    if claim is None:
        return None, problem or "no claim for this session yet; it is seeded at session start"

    if focus is not None:
        claim["focus"] = focus
    for field, values in (replace or {}).items():
        claim[field] = list(dict.fromkeys(values))
    for field, values in (add or {}).items():
        claim[field] = list(dict.fromkeys(list(claim.get(field, [])) + list(values)))
    for field in clear_fields:
        claim.pop(field, None)
    claim["updated_at"] = store.now()

    write_problem = store.write_json(path(root, session_id), claim, SCHEMA)
    return (None, write_problem) if write_problem else (claim, None)


def clear(root, session_id):
    """Remove a session's claim. Returns a problem, or None.

    Missing is success: SessionEnd can fire for a session that never claimed anything, and it can
    fire more than once.
    """
    session_id = store.safe_id(session_id)
    if session_id is None:
        return "session id is not usable as a filename"
    try:
        path(root, session_id).unlink(missing_ok=True)
    except OSError as exc:
        return f"could not clear claim: {exc}"
    return None


def load_all(root):
    """Every claim under this root, plus problems. Never one without the other."""
    return store.read_all(store.sessions_dir(root), SCHEMA)


# The four below are the claim half of #47, and they are here for the same reason the handoff half
# is in `handoffs`: `cli` is in `DECLINED` on the argument that its output is wrong in front of the
# person who typed the command, and that argument is unavailable for a field some other session
# wrote. A claim is exactly that field. `exchange show` renders another session's `focus`, `name`,
# `repos`, `paths` and `tickets`, none of which carry a pattern in the schema and one of which the
# schema describes as "in its own words", and it rendered all five raw for as long as the command
# existed. The handoff half landed one commit earlier with the same reasoning and did not reach
# these, which is the narrower-fix-than-problem shape this repo keeps catching: the commit subject
# said "a record one session writes is data to every other one" and a claim is the other record.
# `describe_settings` is the same shape a third time, one commit later again: the first cut of these
# three fixed `show` and left `claim`'s own echo, which renders the same fields off the same record.
#
# These were written while only a human's terminal read them, ahead of the hook rendering presence
# (#79), so that the stripper was in place before the first injection rather than after it. The
# hook's presence block now reads claims through the same three functions, so the model's context
# is on this path too.


def describe_focus(claim, cap):
    """What a claim says it is doing, in one line, capped and safe to print.

    Stripped before capping, not after. The cap is there to bound what one row can take out of a
    terminal, and counting characters that render as nothing spends the budget on invisible ones -
    so the two operations in the other order give a row shorter than the cap, by an amount the
    reader cannot see and the writer chose.

    Through `store.capped_text` rather than `[:cap]`, so what was cut off is counted. A focus line
    that stops at 240 characters with nothing to say so reads as the whole of what that session
    claimed to be doing, which is the same silent-truncation shape as the lists (#61).
    """
    return store.capped_text(store.printable(claim.get("focus") or "(no focus stated)"), cap)


def describe_name(claim):
    """What to call a claim's session: its name, or the id if it has none.

    `session_id` is held by `store.SAFE_ID` and cannot carry anything the stripper removes; `name`
    is free text copied out of the registry, which is a different session's process. The stripper is
    applied to the result rather than to the `name` branch alone, for the reason `handoffs.describe`
    gives about one rule in one place, and with the same caveat: the id branch is a no-op and is not
    what makes the id safe.
    """
    return store.printable(claim.get("name") or claim["session_id"])


def describe_list(values):
    """A claim's list field, element by element, safe to print.

    Every element rather than the first, which is the same mistake `to_scope` had for one commit and
    is easier to make here: these fields are usually one entry long, so a stripper applied to
    `values[0]` looks right in every case anyone tries by hand.
    """
    return [store.printable(v) for v in values]


def describe_scope(claim, cap):
    """Each list field a claim holds, as `(field, rendered)`, stripped and capped.

    One copy for the two renders of another session's claim, `exchange show` and the hook's
    presence block, so a field or a stripper added to one cannot miss the other the way
    `describe_settings` once missed `show`'s fix.
    """
    return [
        (field, store.capped_list(describe_list(claim[field]), cap))
        for field in LIST_FIELDS
        if claim.get(field)
    ]


def describe_settings(claim):
    """The lines confirming what a claim now holds, for the session that just changed it.

    A second render of a claim, and the one the first cut of the three above missed: `exchange
    claim` echoes what it wrote, and with `--session` the record it echoes belongs to a different
    session, so `focus`, `name` and `tickets` in these lines are that session's text. `repos` and
    `paths` go through `describe_list` too, and not as belt-and-braces: `store.scope_fault` holds
    `--repo`, `--path` and `--set-path` on the way in, but what this echoes is the whole record read
    back off disk, so a scope written before that guard existed, or edited into the file by hand,
    arrives here having passed through nothing. `test_cli.py` writes exactly such a record. The
    importer that arrives with migration step 4 will be a third route, reading scopes out of the
    legacy markdown rather than off a flag - and it is named here as a route that does not exist yet
    rather than one that does, this docstring having already overclaimed once. Missing all of it
    while fixing `show` is the same narrower-than-the-problem shape one command over, twice in one
    branch.

    Uncapped, unlike `describe_focus`. The cap bounds one row of a block that lists every session,
    and this is a session reading back its own write: a confirmation that silently truncated would
    read as a record that had been truncated, which is a worse lie than a long line.
    """
    lines = [f"claimed as {describe_name(claim)}"]
    if claim.get("focus"):
        lines.append(f"  focus: {store.printable(claim['focus'])}")
    for field in LIST_FIELDS:
        if claim.get(field):
            lines.append(f"  {field}: {', '.join(describe_list(claim[field]))}")
    return lines
