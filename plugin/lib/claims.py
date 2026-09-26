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
