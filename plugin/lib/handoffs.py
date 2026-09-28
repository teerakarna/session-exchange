"""Writing handoffs, and reading their status back out of the moves that produced it.

The first thing in this plugin that writes state a *different* session will read, and also the first
thing a different session will write. A claim is written and read by one session, so a wrong claim
misinforms nobody but its author; a handoff is addressed to whoever works in a scope next, which may
be a session that does not exist yet, and is then transitioned by that other session rather than by
its author. Two writers, not one, and everything below follows from that.

**Posting never overwrites.** `post` refuses an id that is already on disk rather than replacing it.
An id collision means two handoffs, and silently keeping one is the failure mode this project is
about - the loss is invisible to both the sender and the recipient, and there is no later command
whose output looks wrong. Ids carry a random suffix precisely so a collision is a bug rather than
ordinary contention, which is why it is safe to treat one as a refusal instead of retrying. The
refusal is `os.link` rather than a check followed by a write: see `store.create_json`.

**Status is not a field.** It is derived from the transitions in `handoffs/<id>/`, one file per
move, and the handoff file itself is written once by the sender and never touched again. Two things
follow. There is no `status` that can contradict the history, because there is no second copy to
contradict; and there is no read-modify-write, because a move creates a new name rather than
rewriting an existing one, so two sessions moving the same handoff at the same moment both get their
move recorded.

That is #44, and it is worth saying what the version before it did, because the bug was not where
it looks. `status` and a `history` array lived in the handoff file, `set_status` read them,
appended and wrote back, and a check on the way out reported a record whose two halves disagreed.
Two concurrent moves both read the same history and the later write dropped the earlier entry -
and the file left behind was internally consistent, so the check reported nothing. The invariant
being policed was precisely the one a lost update preserves.

`post` writes no transitions at all. A first entry restating `created` and `open` is not a record of
anything, and an empty directory is unambiguous: never changed since it was posted.
"""

from __future__ import annotations

import pathlib
import secrets
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import store
import validate

SCHEMA = validate.load("handoff")
TRANSITION = validate.load("transition")

OPEN = "open"
ACCEPTED = "accepted"
CLOSED = "closed"
STATUSES = (OPEN, ACCEPTED, CLOSED)

# Six hex characters, so a same-second collision needs a 1-in-16-million coincidence rather than two
# sessions posting at once. The point is not the odds, it is that they let `post` refuse a collision
# rather than retry: without a suffix, two handoffs posted in the same second would collide as a
# matter of course, and the only safe behaviour would be to retry, which quietly turns a real
# duplicate into a second row nobody compares.
SUFFIX_BYTES = 3


def path(root, handoff_id):
    return store.handoffs_dir(root) / f"{handoff_id}.json"


def new_id(at=None):
    """A sortable id: the posting timestamp, then a random suffix.

    Sortable because the directory listing is the only ordering handoffs have - nothing indexes them
    and `read_all` sorts by filename - so a lexical sort has to be a chronological one. The `:` and
    `-` of the timestamp are stripped because the id doubles as the filename, and `store.SAFE_ID`
    refuses both, which is a constraint worth keeping rather than widening for cosmetics.
    """
    stamp = (at or store.now()).replace("-", "").replace(":", "")
    return f"{stamp}-{secrets.token_hex(SUFFIX_BYTES)}"


def to_scope(repo=None, paths=(), session_id=None):
    """The `to` block, or a problem. Exactly one addressing mode, and never neither.

    The schema's `oneOf` would catch both-at-once on the way to disk, but not with a sentence anyone
    wants to read, and it cannot catch neither-given at all: an empty `to` fails as "does not match
    any of the allowed forms", which is true and says nothing about which flag they forgot.
    """
    if repo and session_id:
        return None, "a handoff goes to a scope or to one session, not both"
    if session_id:
        # Before the `session_id` return rather than after it. `--path` has no meaning for a session
        # scope, and the first version of this function returned here and left the paths behind: the
        # handoff posted, exit 0, and the narrowing the caller typed was simply not in the record.
        # There was already a refusal written for paths-with-no-repo four lines below, which this
        # return jumped over - a silent truncation next to the error message for it.
        if paths:
            return None, "--path narrows a repo scope, so it cannot go with --session"
        return {"session_id": session_id}, None
    if repo:
        scope = {"repo": repo}
        if paths:
            scope["paths"] = list(dict.fromkeys(paths))
        return scope, None
    if paths:
        return None, "--path narrows a repo scope, so it needs --repo as well"
    return None, "say who it is for: --repo (optionally with --path) or --session"


def post(root, to, body, cwd, session_id=None, name=None, handoff_id=None, at=None):
    """Write a new handoff. Returns `(record, problem)`.

    `cwd` rather than nothing identifies the sender even when the session id could not be worked
    out, which is the case for an entry lifted out of a ledger and also for a terminal that is not
    inside a session the registry knows. The schema requires `cwd` for exactly that reason.
    """
    if not (body or "").strip():
        return None, "a handoff with no body says nothing; give it one"

    at = at or store.now()
    handoff_id = handoff_id or new_id(at)
    if store.safe_id(handoff_id) is None:
        return None, f"{handoff_id!r} cannot be a filename, so it cannot be a handoff id"

    record = {
        "id": handoff_id,
        "from": {"cwd": str(cwd)},
        "to": to,
        "created": at,
        "body": body.strip(),
    }
    if session_id:
        record["from"]["session_id"] = session_id
    if name:
        record["from"]["name"] = name

    # `create_json`, so "never a replace" is the filesystem refusing a name that exists rather
    # than this function checking first and writing second. The check-then-write version was here,
    # and its window between the two was small enough to be invisible and real enough to lose a
    # handoff - the loss being invisible to both ends is the whole reason this rule exists.
    problem = store.create_json(path(root, handoff_id), record, SCHEMA)
    return (None, problem) if problem else (record, None)


def transition_path(root, handoff_id, after):
    """Where one move goes: its causal position, then a random suffix.

    The position leads so that a directory listing reads in order for a human. It is not what the
    reader orders by - `transitions` sorts on the field, so the padding here is cosmetic and cannot
    be the wrong width. The suffix is what makes two concurrent writers at the same position two
    files rather than one, and `create_json` turns the remaining one-in-sixteen-million case into a
    refusal rather than a silent overwrite.
    """
    name = f"{after:04d}-{secrets.token_hex(SUFFIX_BYTES)}.json"
    return store.transitions_dir(root, handoff_id) / name


def transitions(root, handoff_id):
    """Every recorded move on one handoff, oldest first, plus problems.

    Ordered by `after` rather than by the clock. `at` is seconds, and accepting then closing
    inside one second gives two moves the same timestamp with no way to tell them apart - the
    first version of this sorted by filename, and a handoff read back as accepted after it had
    been closed. Sorting on the field the writer computed from what it read puts the serialised
    case in the right order and leaves only the genuinely concurrent one tied, which is what
    `state_of` reports.
    """
    entries, problems = store.read_all(store.transitions_dir(root, handoff_id), TRANSITION)
    return sorted(entries, key=lambda entry: entry["after"]), problems


def set_status(root, handoff_id, status, by=None, note=None, at=None):
    """Move a handoff to `status` by writing the move. Returns `(transition, problem)`.

    One new file, created rather than replaced, so nothing is read and written back and nothing
    another session wrote in between can be dropped.

    Refuses a move to the status it already has. "Close a closed handoff" is not a no-op worth
    absorbing: either the caller is looking at a stale render, or two sessions are answering the
    same thing, and both are worth a line of output. The guard is still best-effort - two moves
    that genuinely race both read the same state and both pass it. What changed is the outcome.
    Before, one of the two entries was gone and nothing said so; now there are two truthful
    records of two sessions closing the same handoff, which is what happened.
    """
    if status not in STATUSES:
        return None, f"{status!r} is not a handoff status; one of {', '.join(STATUSES)}"

    if store.safe_id(handoff_id) is None:
        return None, f"{handoff_id!r} cannot be a filename, so it cannot be a handoff id"
    # Read to confirm the handoff exists and validates, never to modify it. A transition filed under
    # an id nothing posted is a status for a handoff no reader will ever go looking for.
    record, problem = store.read_json(path(root, handoff_id), SCHEMA)
    if record is None:
        return None, problem or f"no handoff with id {handoff_id} under this root"
    # No second `if problem` after that. `read_json`'s contract is that every failure returns a
    # `None` record, so a record in hand means there is no problem to check for, and the check that
    # used to be here was unfalsifiable: mutating it to `if False:` left the suite green, which this
    # repo treats as a defect rather than as coverage.

    seen, problems = transitions(root, handoff_id)
    current, tie = _status_of(handoff_id, seen)
    if problems or tie:
        # Refusing rather than guessing. An unreadable move could be the latest one and a contested
        # position has no latest one, so `current` may not be current, and moving from a status that
        # is not the real one is how a closed handoff comes back open.
        return None, "; ".join([*problems, *([tie] if tie else [])])
    if current == status:
        return None, f"{handoff_id} is already {status}"

    # `len(seen)`, so the move records what its writer had read. Two sessions acting on the same
    # state land on the same number and both files are written; nothing is lost, and the tie is what
    # `state_of` reports rather than something it resolves.
    entry = {"at": at or store.now(), "status": status, "after": len(seen)}
    if by:
        entry["by"] = by
    if note:
        entry["note"] = note

    problem = store.create_json(transition_path(root, handoff_id, len(seen)), entry, TRANSITION)
    return (None, problem) if problem else (entry, None)


def state_of(root, handoff_id):
    """The current status of one handoff, and anything wrong with how it got there.

    Returns `(status, problems)`. No moves at all means `open`: `post` writes none, so an empty
    directory says "never changed since it was posted" and nothing else.

    A problem never suppresses the status. A caller rendering a list must be able to show the row
    *and* the fault, because dropping the row would hide a handoff, which is worse than showing one
    whose state is in question.
    """
    entries, problems = transitions(root, handoff_id)
    status, tie = _status_of(handoff_id, entries)
    return status, problems + ([tie] if tie else [])


def _status_of(handoff_id, entries):
    """The last status in an ordered list of moves, and a problem if the last position is contested.

    Split out because `set_status` needs this without re-reading the directory it has just read, and
    the two must not be able to disagree about what the current status is.

    Two moves sharing an `after` were written against the same state, so they are concurrent and
    nothing here can say which came first. Two concurrent *identical* closes are not a problem -
    both are true, and the handoff is closed either way. Two that disagree are reported and not
    resolved, for the same reason the old status-against-history disagreement was.
    """
    if not entries:
        return OPEN, None
    last = entries[-1]
    tied = [e for e in entries if e["after"] == last["after"] and e["status"] != last["status"]]
    if tied:
        return last["status"], (
            f"{handoff_id} has two moves at position {last['after']} that disagree "
            f"({tied[0]['status']!r} and {last['status']!r}); they were made against the same "
            "state, so which came first cannot be worked out from here"
        )
    return last["status"], None


def load_all(root):
    """Every handoff under this root as `(record, status)`, plus problems.

    A pair rather than a `status` key added to the record on the way past. Nothing in memory then
    looks like a field that is on disk, and a caller has to name which half it is reading - which is
    the property this whole module is arranged around.
    """
    records, problems = store.read_all(store.handoffs_dir(root), SCHEMA)
    pairs = []
    for record in records:
        # `read_all` hands back contents without filenames, so the id inside the file is what finds
        # the moves. A hand-edited id would point at a directory that does not exist, `state_of`
        # would say `open`, and a closed handoff would quietly come back. One stat says otherwise:
        # the id has to name the file it was read from.
        if not path(root, record["id"]).is_file():
            problems.append(
                f"a handoff file holds the id {record['id']} but is not named after it; its "
                "moves live under that id, so the status below it is not to be trusted"
            )
        status, faults = state_of(root, record["id"])
        problems += faults
        pairs.append((record, status))
    return pairs, problems


def describe(to):
    """The addressing, in one short phrase, for a human reading a list."""
    if "session_id" in to:
        return f"session {to['session_id']}"
    paths = to.get("paths")
    return f"{to['repo']}: {', '.join(paths)}" if paths else to["repo"]
