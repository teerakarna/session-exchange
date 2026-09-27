"""Writing handoffs, and reading them back with the one disagreement that cannot be tolerated.

The first thing in this plugin that writes state a *different* session will read. A claim is written
and read by one session, so a wrong claim misinforms nobody but its author; a handoff is addressed
to whoever works in a scope next, which may be a session that does not exist yet. Two rules follow
from that and everything else here is detail.

**Posting never overwrites.** `post` refuses an id that is already on disk rather than replacing it.
An id collision means two handoffs, and silently keeping one is the failure mode this project is
about - the loss is invisible to both the sender and the recipient, and there is no later command
whose output looks wrong. Ids carry a random suffix precisely so a collision is a bug rather than
ordinary contention, which is why it is safe to treat one as a refusal instead of retrying.

**`status` is derived from `history`, not maintained beside it.** Two fields that can disagree
cannot say which one was read, and that is the defect class this repo keeps finding in new shapes.
So `set_status` appends to `history` and takes `status` from what it appended, in one write. Reading
enforces the same thing from the other side: a record whose `status` contradicts the last history
entry is reported as a problem rather than resolved in favour of either, because nothing here wrote
it and guessing which half is stale is how a closed handoff comes back open.

`post` writes no history at all. A single entry restating `created` and `open` is not a record of
anything, and an empty history is unambiguous: never changed since it was posted.
"""

from __future__ import annotations

import pathlib
import secrets
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import store
import validate

SCHEMA = validate.load("handoff")

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

    target = path(root, handoff_id)
    if target.exists():
        # Never a replace. See the module docstring: the loss would be invisible to both ends.
        return None, f"a handoff with id {handoff_id} already exists; refusing to overwrite it"

    record = {
        "id": handoff_id,
        "from": {"cwd": str(cwd)},
        "to": to,
        "created": at,
        "status": OPEN,
        "body": body.strip(),
    }
    if session_id:
        record["from"]["session_id"] = session_id
    if name:
        record["from"]["name"] = name

    problem = store.write_json(target, record, SCHEMA)
    return (None, problem) if problem else (record, None)


def set_status(root, handoff_id, status, by=None, note=None, at=None):
    """Move a handoff to `status`, recording the move. Returns `(record, problem)`.

    Refuses a move to the status it already has. "Close a closed handoff" is not a no-op worth
    absorbing: either the caller is looking at a stale render, or two sessions are answering the
    same thing, and both are worth one line of output rather than a second identical history entry.
    """
    if status not in STATUSES:
        return None, f"{status!r} is not a handoff status; one of {', '.join(STATUSES)}"

    if store.safe_id(handoff_id) is None:
        return None, f"{handoff_id!r} cannot be a filename, so it cannot be a handoff id"
    record, problem = store.read_json(path(root, handoff_id), SCHEMA)
    if record is None:
        return None, problem or f"no handoff with id {handoff_id} under this root"
    # No second `if problem` after that. `read_json`'s contract is that every failure returns a
    # `None` record, so a record in hand means there is no problem to check for, and the check that
    # used to be here was unfalsifiable: mutating it to `if False:` left the suite green, which this
    # repo treats as a defect rather than as coverage.

    current, disagreement = state_of(record)
    if disagreement:
        # Refusing rather than repairing. A record whose two halves disagree was not written here,
        # and appending to it would make this module the author of a history it cannot vouch for.
        return None, disagreement
    if current == status:
        return None, f"{handoff_id} is already {status}"

    entry = {"at": at or store.now(), "status": status}
    if by:
        entry["by"] = by
    if note:
        entry["note"] = note
    record["history"] = [*record.get("history", []), entry]
    record["status"] = entry["status"]

    problem = store.write_json(path(root, handoff_id), record, SCHEMA)
    return (None, problem) if problem else (record, None)


def state_of(record):
    """The current status, and a problem if the record's two halves disagree.

    Returns `(status, problem)`. The status is still returned alongside a problem, because a caller
    rendering a list must be able to show the row *and* the fault: dropping the row would hide a
    handoff, which is worse than showing one whose state is in question.
    """
    history = record.get("history") or []
    stated = record.get("status")
    if not history:
        return stated, None
    last = history[-1].get("status")
    if last != stated:
        return stated, (
            f"{record.get('id')} says it is {stated!r} while its last history entry says "
            f"{last!r}; something other than `exchange` wrote it and which half is stale "
            "cannot be worked out from here"
        )
    return stated, None


def load_all(root):
    """Every handoff under this root, plus problems. Never one without the other.

    The disagreement check runs here and not in `store.read_all`, because it is a rule about what a
    handoff means rather than about whether a file parses. A record that fails it is still returned.
    """
    records, problems = store.read_all(store.handoffs_dir(root), SCHEMA)
    for record in records:
        _, problem = state_of(record)
        if problem:
            problems.append(problem)
    return records, problems


def describe(to):
    """The addressing, in one short phrase, for a human reading a list."""
    if "session_id" in to:
        return f"session {to['session_id']}"
    paths = to.get("paths")
    return f"{to['repo']}: {', '.join(paths)}" if paths else to["repo"]
