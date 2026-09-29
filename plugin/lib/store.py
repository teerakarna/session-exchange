"""Where state lives under a root, and how it is written.

Layout, under a root that `exchange_root` resolved and this module never guesses:

    <root>/.claude/exchange.json                       the marker, which is also the config
    <root>/.claude/exchange/sessions/<session_id>.json one claim per session
    <root>/.claude/exchange/handoffs/<id>.json         one file per handoff, written once
    <root>/.claude/exchange/handoffs/<id>.d/<after>-<n>.json  one file per status change
    <root>/.claude/exchange/EXCHANGE.md                narrative, for humans and sessions

One file per writer, never a shared append target. Six concurrent sessions on one file is the
contention this layout exists to avoid, and it is also why no write here needs a lock.

A claim has one writer by nature - the session it describes - so that much was free. A handoff does
not: the sender writes the record and some other session moves it on, which is two writers, and for
a while the second one appended to an array inside the first one's file with no lock around the
read-modify-write. Two concurrent moves both read the same history and the later write dropped the
earlier entry, and because the surviving file was internally consistent nothing downstream had
anything to report. The fix was not a lock, it was to stop violating the rule at the top of this
docstring: a status change is now its own file under `<id>/`, so the only writer of any file here is
still the one that created it. See #44.
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


def transitions_dir(root, handoff_id):
    """Where one handoff's status changes live, one file per change.

    A directory beside `<id>.json` rather than an array inside it, so the handoff file stays what
    `post` wrote.

    `.d` rather than the bare id, which is what this was first: an id may contain a dot, so an id of
    `note.json` gave a record at `handoffs/note.json.json` and a moves directory at
    `handoffs/note.json`, which `read_all`'s `*.json` glob then tried to parse as a record. The
    result was a permanent "Is a directory" problem on every read, plus a later `post` of the id
    `note` refused for colliding with a name nobody had written. The suffix cannot be a record's
    name, so the two namespaces cannot overlap whatever the id is - which is worth more than a rule
    that ids must not end in `.json`, because nothing has to remember it.
    """
    return handoffs_dir(root) / f"{handoff_id}.d"


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


def printable(value):
    """`value` with every character a terminal acts on rather than shows removed.

    For text one session wrote and another session's terminal renders. `safe_id` is the same lesson
    one field over - its docstring is about a newline ending a markdown row early - and the reason
    this is a second function rather than a second caller of that one is that prose has to survive
    it. An id may be refused; a body has to be shown.

    `str.isprintable` rather than a blacklist of the escapes seen so far. It already excludes every
    C0 and C1 control, so `\\033`, `\\r` and `\\007` go without being named, and it also excludes
    the `Cf` category, which is where the bidi overrides live - a class nobody here thought of, kept
    out by picking the question "would a terminal show this" over "is this one of the bad ones".
    Space is printable and stays. Tab is not and goes, which is correct for a one-line preview: the
    character is there to move the cursor.

    Dropping rather than escaping. `repr` was the alternative and it backslashes every quote and
    backslash in ordinary prose, so the common case pays for the rare one. Dropping does mean the
    rendered line can differ from the stored one, which is worth stating plainly - but that is
    already true of the text this exists for, and an erase-line escape makes the difference the
    reader's problem instead of the writer's.
    """
    return "".join(ch for ch in value if ch.isprintable())


def _staged(path, obj, schema):
    """Validate, then write a temp file beside the target. Returns `(tmp, problem)`.

    Both writers share this rather than each carrying a copy. "An invalid object never reaches disk"
    is then one rule in one place, which is also one entry in the mutation table: two copies of a
    refusal are two things that can drift, and only one of them would be the one under test.

    Validating before writing rather than after means a reader never has to distinguish "corrupt"
    from "written by a newer version".
    """
    if schema is not None:
        problems = validate.validate(obj, schema, path.name)
        if problems:
            return None, f"refusing to write {path}: " + "; ".join(problems)

    tmp = path.with_name(f".tmp-{os.getpid()}-{path.name}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return None, f"could not write {path}: {exc}"
    return tmp, None


def write_json(path, obj, schema=None):
    """Validate, then write atomically, replacing whatever was there. Returns a problem or None.

    A temp file in the same directory plus `os.replace`, which is atomic on the same filesystem. A
    reader mid-write therefore sees the old file or the new one, never a half of either.
    """
    path = pathlib.Path(path)
    tmp, problem = _staged(path, obj, schema)
    if problem:
        return problem
    try:
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return f"could not write {path}: {exc}"
    return None


def create_json(path, obj, schema=None):
    """Like `write_json`, but refuses a path that already exists. Returns a problem, or None.

    `os.link` rather than `path.exists()` and then a write. The check-then-write version has a
    window between the two in which another process can create the file, and both writers then
    think they created it - which is the shape of every bug in this repo's list. `link` is one
    syscall that either creates the name or fails with `EEXIST`, so "first writer wins" is the
    filesystem's answer rather than a guard's, and there is no window to lose.

    The temp file is hardlinked into place and then unlinked, so a reader that globs the directory
    mid-write sees the target or nothing, and never the `.tmp-` name under a name it would read.
    """
    path = pathlib.Path(path)
    tmp, problem = _staged(path, obj, schema)
    if problem:
        return problem
    try:
        os.link(tmp, path)
    except FileExistsError:
        return f"{path.name} already exists; refusing to overwrite it"
    except OSError as exc:
        return f"could not write {path}: {exc}"
    finally:
        tmp.unlink(missing_ok=True)
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


def read_each(directory, schema=None):
    """Every `*.json` in a directory as `(path, obj)`, sorted. Returns `(found, problems)`.

    Both halves are returned because one unreadable file must not hide the rest, and the rest
    passing must not hide the unreadable one.

    The path comes back because for some callers the filename is part of what was read. `read_all`
    is this with the paths dropped, and is what most callers want; a caller that has to check the
    contents against the name they came out of cannot use it, because the name is exactly what it
    discards. "The id in this file names this file" is unfalsifiable without this.

    The `.tmp-` filter is not tidiness. A writer killed between `_staged` and the link leaves one
    behind, and a reader that counted it would be counting a move that was never made.
    """
    directory = pathlib.Path(directory)
    found, problems = [], []
    try:
        paths = sorted(p for p in directory.glob("*.json") if not p.name.startswith(".tmp-"))
    except OSError as exc:
        return found, [f"could not list {directory}: {exc}"]
    for path in paths:
        obj, problem = read_json(path, schema)
        if problem:
            problems.append(problem)
        elif obj is not None:
            found.append((path, obj))
    return found, problems


def read_all(directory, schema=None):
    """Every `*.json` in a directory, sorted. Returns `(objects, problems)`."""
    found, problems = read_each(directory, schema)
    return [obj for _, obj in found], problems


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
