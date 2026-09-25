"""Where state lives under a root, and how it is written.

Layout, under a root that `exchange_root` resolved and this module never guesses:

    <root>/.claude/exchange.json                       the marker, which is also the config
    <root>/.claude/exchange/sessions/<session_id>.json one claim per session
    <root>/.claude/exchange/handoffs/<id>.json         one file per handoff
    <root>/.claude/exchange/EXCHANGE.md                narrative, for humans and sessions

One file per writer, never a shared append target. Six concurrent sessions on one file is the
contention this layout exists to avoid, and it is also why no write here needs a lock: the only
writer of a session's claim is that session.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re

import validate

# Also a filename, so anything that could climb out of the directory is refused rather than
# sanitised. Rejecting is honest; quietly rewriting an identifier is how two sessions end up
# sharing one file.
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")

STORE = "exchange"


def now():
    """UTC, seconds, always Z. The one timestamp format anything here writes."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_dir(root):
    return pathlib.Path(root) / ".claude" / STORE


def sessions_dir(root):
    return store_dir(root) / "sessions"


def handoffs_dir(root):
    return store_dir(root) / "handoffs"


def markdown(root):
    return store_dir(root) / "EXCHANGE.md"


def safe_id(value):
    """The identifier, or None if it cannot be a filename.

    `fullmatch`, not `match`, and the difference is not the obvious one: the pattern is anchored at
    both ends already, but Python's `$` also matches just *before* a trailing newline. So `match`
    accepted `"sess-1\\n"`, wrote a claim under that name, and put the newline in the `session_id`
    field, where presence rendering will later put it inside a markdown table cell and end the row
    early. The guard read as tight and let through the one character that matters most.
    """
    return value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None


def write_json(path, obj, schema=None):
    """Validate, then write atomically. Returns a problem string, or None on success.

    Validating before writing rather than after means an invalid file never reaches disk, so a
    reader never has to distinguish "corrupt" from "written by a newer version".

    The write is a temp file in the same directory plus `os.replace`, which is atomic on the same
    filesystem. A reader mid-write therefore sees the old file or the new one, never a half of
    either.
    """
    path = pathlib.Path(path)
    if schema is not None:
        problems = validate.validate(obj, schema, path.name)
        if problems:
            return f"refusing to write {path}: " + "; ".join(problems)

    tmp = path.with_name(f".tmp-{os.getpid()}-{path.name}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return f"could not write {path}: {exc}"
    return None


def read_json(path, schema=None):
    """Returns `(obj, problem)`. A file that exists and does not parse is never `(None, None)`.

    That distinction is the whole contract: a missing file means nothing is claimed, an unreadable
    one means something is wrong, and collapsing the two is how a broken parser read as a quiet day
    for ten days.
    """
    path = pathlib.Path(path)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, f"{path.name} could not be read: {exc}"
    if schema is not None:
        problems = validate.validate(obj, schema, path.name)
        if problems:
            return None, f"{path.name} is invalid: " + "; ".join(problems)
    return obj, None


def read_all(directory, schema=None):
    """Every `*.json` in a directory, sorted. Returns `(objects, problems)`.

    Both halves are returned because one unreadable file must not hide the rest, and the rest
    passing must not hide the unreadable one.
    """
    directory = pathlib.Path(directory)
    objects, problems = [], []
    try:
        paths = sorted(p for p in directory.glob("*.json") if not p.name.startswith(".tmp-"))
    except OSError as exc:
        return objects, [f"could not list {directory}: {exc}"]
    for path in paths:
        obj, problem = read_json(path, schema)
        if problem:
            problems.append(problem)
        elif obj is not None:
            objects.append(obj)
    return objects, problems


def config(root):
    """The marker's contents with defaults filled in, plus any problem reading it.

    Defaults come from the schema so they are stated once. A marker that exists and is invalid
    yields the defaults *and* a problem: refusing to render presence because a cap is misspelt
    would be the wrong trade, but doing it silently would be worse.
    """
    schema = validate.load("exchange")
    defaults = {
        key: spec["default"] for key, spec in schema["properties"].items() if "default" in spec
    }
    obj, problem = read_json(pathlib.Path(root) / ".claude" / "exchange.json", schema)
    if obj is None:
        return dict(defaults, name=pathlib.Path(root).name), problem
    return dict(defaults, **obj), None
