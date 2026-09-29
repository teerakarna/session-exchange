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

# What `_staged` names a file it has not linked into place yet. One constant rather than the
# literal in each of the four places that care, because two of them are filters whose job is to
# keep these files from being read and a third is the diagnostic that reports one: a copy that
# drifted would not fail, it would quietly start reading half-written records.
TMP_PREFIX = ".tmp-"


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
    out by picking the question "would a terminal show this" over "is this one of the bad ones". Tab
    is not printable and goes, which is correct for a one-line preview: the character is there to
    move the cursor.

    What that question costs, stated rather than discovered later. U+0020 is the only space it
    keeps: every other `Zs` goes, including U+3000, which is the ordinary space in Japanese and
    Chinese prose, and U+00A0, which arrives in anything pasted out of a browser. `Cf` takes the
    bidi overrides and also ZWJ and ZWNJ, which are orthographic rather than decorative - dropping
    them joins words in Persian, changes which glyph an Indic conjunct renders as, and splits an
    emoji family into three people. Accented Latin, Greek, Cyrillic, CJK, Thai, Arabic, Hebrew,
    Devanagari, combining accents and single emoji all survive, which is the half that matters for
    prose. The trade is accepted because the alternative is naming escapes one at a time and the
    next one is always the one nobody named, but it is a trade and not a free win.

    Dropping rather than escaping. `repr` was the alternative and it backslashes every quote and
    backslash in ordinary prose, so the common case pays for the rare one. Dropping does mean the
    rendered line can differ from the stored one, which is worth stating plainly - but that is
    already true of the text this exists for, and an erase-line escape makes the difference the
    reader's problem instead of the writer's.
    """
    return "".join(ch for ch in value if ch.isprintable())


def capped_text(value, cap):
    """`value` bounded to `cap` characters, with whatever was cut off counted rather than dropped.

    The text half of what `cli._capped` does for a list, and the same argument: a line that stops at
    the cap silently reads as the whole of what the sender wrote, so nobody goes looking for the
    rest. `[:cap]` was what the one capped render in this plugin did, and the row that went into
    every session at 23 KB is why any of these caps exist at all.

    Applied after `printable` by every caller here, for the reason `claims.describe_focus` gives:
    characters that render as nothing still spend the budget, so capping first gives a line shorter
    than the cap by an amount the reader cannot see and the writer chose.
    """
    if len(value) <= cap:
        return value
    return f"{value[:cap]} +{len(value) - cap} more chars"


def scope_fault(flag, value):
    """Why `value` cannot be a root-relative scope path, or None.

    Here rather than in either record's module because both records have these fields and they mean
    the same thing in both: a handoff's `to.repo` and `to.paths`, and a claim's `repos` and `paths`.
    The whole point of the shape is that the two get compared - #46 was filed on the sentence
    "matching a handoff to a recipient means comparing `to.repo` against a claim's `repos`" - so a
    guard on one side of that comparison and not the other contains nothing. It was on the handoff
    side alone for one commit. `store` is the module both importers already have.

    Root-relative is what both schemas say these are, and `minLength: 1` was the whole of what they
    enforced. Not a pattern in the schemas, for the reason `to`'s docstring gives about `oneOf`: a
    pattern refuses with "does not match", and the useful sentence names which flag and which shape.

    Nothing dereferences either field as a path today, so this is containment ahead of the matcher
    rather than a fix for a live escape - one function now against two consumers later. The three
    cases are separate messages because they are separate mistakes: a leading `/` is usually a
    habit, a `..` is usually a misunderstanding of what the field is relative to, and an invisible
    character is usually a paste.

    Split on `/` rather than resolved with `pathlib`: resolving asks the filesystem what exists,
    which makes the refusal depend on the machine it runs on. `..` as a whole component, so `a..b`
    and `..bashrc` stay legal, which they are.

    The `printable` case is a refusal and not a strip, and that is the load-bearing part rather than
    its position in the list. `\\t/etc` does not start with `/`, so the check above passes it, and
    every renderer here strips the tab and shows `/etc` - the exact shape that check exists to
    refuse, manufactured after it ran. Stripping on the way in would have the same problem one layer
    down. A field that gets compared cannot afford it for a second reason that has nothing to do
    with terminals: two scopes differing only by a character nothing displays look identical to the
    person deciding whether they collide. So a scope is stored only if it is the same string the
    reader sees.

    Order between the three changes which message comes back and nothing else, all three being
    refusals. It is first because an invisible character is the one a reader cannot diagnose from
    the other two messages.

    That message names codepoints, and it has to. It cannot carry the value: printing the raw one
    puts the escape back into the line that refuses it. It cannot carry the stripped one alone
    either, which is what it did first - `--path` holding a tab refused with "rather than shows:
    /etc", and `/etc` is a string the typist can see nothing wrong with, so the refusal read as
    arbitrary and there was nothing to act on. For a value that is invisible end to end the stripped
    form is empty and the message said nothing at all. `U+0009` is actionable; the shape it renders
    as stays in the message after it, because that is the half that says why anyone cares.

    The predicate is `printable` applied to one character rather than a second copy of
    `isprintable`, for the reason `_staged` gives about one refusal in one place: two copies of it
    drift and only one is the one under test.

    Wider than "characters a terminal acts on": U+00A0 and U+3000 are refused too, and `printable`'s
    docstring is explicit that it drops them. For prose that is a cost. For a scope it is the point.
    A path component differing from another only by a non-breaking space is the collision case this
    guard exists for, it is what #62 is about, and a store holding both spellings cannot tell anyone
    which one they meant. So the refusal stays wide and the message names the codepoint, rather than
    the refusal narrowing to `Cc` and `Cf` and letting the two spellings in.
    """
    shown = printable(value)
    if shown != value:
        dropped = ", ".join(
            f"U+{ord(ch):04X}" for ch in dict.fromkeys(value) if printable(ch) != ch
        )
        return (
            f"{flag} cannot hold characters a terminal does not show: {dropped}. "
            f"Without them it reads as {shown!r}"
        )
    if value.startswith("/"):
        return f"{flag} is relative to the root, so it cannot start with /: {value}"
    if ".." in value.split("/"):
        return f"{flag} cannot climb out of the root with ..: {value}"
    return None


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

    tmp = path.with_name(f"{TMP_PREFIX}{os.getpid()}-{path.name}")
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
        paths = sorted(p for p in directory.glob("*.json") if not p.name.startswith(TMP_PREFIX))
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


def names(directory, pattern):
    """Paths matching `pattern` in `directory`, sorted. Returns `(paths, problems)`.

    For the diagnostics that look at filenames rather than at contents, which `read_each` cannot
    answer: it globs `*.json` and drops the names that are not records, and those names are exactly
    what a reader of this is asking about. A missing directory is not a fault here - an exchange
    with no handoffs yet has no handoffs directory - so it comes back as nothing found rather than
    as a problem.

    The `OSError` half is the same unfalsifiable branch `read_each` carries, and it is stated
    rather than left to be discovered: `glob` on a missing directory returns nothing, so reaching
    it takes a directory that exists and cannot be listed. It is here so that a broken store is one
    line in `doctor`'s output instead of a traceback over the top of the rest of the report.
    """
    directory = pathlib.Path(directory)
    try:
        return sorted(directory.glob(pattern)), []
    except OSError as exc:
        return [], [f"could not list {directory}: {exc}"]


def litter(root):
    """Half-written files left behind under this root, as problems.

    #53. `_staged` writes a `.tmp-` beside its target and both writers above remove it, so one still
    on disk is a writer killed in between. `read_each` filters the name, which makes the effect of
    that "the write did not happen" - the right outcome, and also the reason nothing has ever
    mentioned the file. That filter is load-bearing for correctness rather than for tidiness now: a
    reader that counted a temp file would count a move into the position `set_status` computes from
    what it read. A file that is both inert and invisible is one property too many, because the day
    the filter goes is the day the litter starts being read.

    Every directory this store writes into, not just the handoffs. `claims` goes through `_staged`
    too, the moves live one directory further down again, and the marker itself is a staged write
    into the directory above all of them - so an `init` killed mid-write leaves litter as well. A
    sweep that covered the record directory alone would be this repo's recurring defect, a fix
    narrower than the thing it fixes, and the first cut of this one was exactly that.
    """
    directories = [marker_path(root).parent, sessions_dir(root), handoffs_dir(root)]
    moves, problems = names(handoffs_dir(root), "*.d")
    directories += [path for path in moves if path.is_dir()]
    for directory in directories:
        found, faults = names(directory, f"{TMP_PREFIX}*")
        problems += faults
        for path in found:
            problems.append(
                f"{directory.name}/{path.name} is a half-written file left behind by a writer that "
                "was killed; readers skip it, so whatever it was going to say did not get said. "
                "Safe to delete."
            )
    return problems


def marker_path(root):
    """Where the marker for `root` lives, which is also where its config lives.

    One function rather than the same three path components in `init`, in `doctor` and in `config`,
    for the reason `TMP_PREFIX` is a constant: a copy that drifted would not fail. `init` would
    write a marker `config` does not read, and every cap would silently stay at its default while a
    file sitting in the repo said otherwise.
    """
    return pathlib.Path(root) / ".claude" / "exchange.json"


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
    obj, problem = read_json(marker_path(root), schema)
    if obj is None:
        return dict(defaults, name=pathlib.Path(root).name), problem
    return dict(defaults, **obj), None
