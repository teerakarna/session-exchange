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

**Status is not a field.** It is derived from the transitions in `handoffs/<id>.d/`, one file per
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
        fault = store.scope_fault("--repo", repo)
        if fault:
            return None, fault
        scope = {"repo": repo}
        if paths:
            # Every element, not the first one. `paths` is the half of this that is easy to leave
            # out: it is optional, it is usually one entry, and a guard written for `repo` alone
            # reads as done. The schema constrains the two identically, so a caller that can put a
            # `..` in one can put it in the other.
            for path in paths:
                fault = store.scope_fault("--path", path)
                if fault:
                    return None, fault
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
    # A moves directory can outlive its record - `rm handoffs/<id>.json` leaves one behind, and
    # nothing iterates directories, so it is invisible until an id lands on it again. Posting into
    # it would hand a brand-new handoff someone else's status the moment it was written: posted,
    # exit 0, and it reads as closed. That is this project's founding failure with a new cause, so
    # the moves are treated the same way as the record - a name already taken is a refusal, not a
    # merge.
    if store.transitions_dir(root, handoff_id).exists():
        return None, f"{handoff_id} already has moves recorded under it; refusing to post over them"

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
    # Named for the handoff on the way out. A move file deliberately does not carry the id, and its
    # name is a position, so `0001-a3f2.json could not be read` on its own points at nothing anyone
    # can act on - and two handoffs with one bad move each produce two identical lines.
    faults = [f"{handoff_id}: {problem}" for problem in problems]
    return sorted(entries, key=lambda entry: entry["after"]), faults


def _moving(root, handoff_id, status):
    """What both move verbs check before writing anything.

    Returns `(seen, problems, refusal)`: the moves already recorded, whatever went wrong reading
    them, and a refusal that stands whatever the caller was trying to do. Three values rather than
    two because the two verbs part company on `problems` - `set_status` folds it in with the contest
    report and `resolve` refuses on it alone - and a shared function that decided that would be
    deciding the one thing they disagree about.

    Shared so that "which ids and which statuses exist, and does the record read" is one answer.
    `resolve` is a second writer of moves, and a second copy of those three refusals would be three
    things that drift with only one of them the one under test.
    """
    if status not in STATUSES:
        return None, [], f"{status!r} is not a handoff status; one of {', '.join(STATUSES)}"
    if store.safe_id(handoff_id) is None:
        return None, [], f"{handoff_id!r} cannot be a filename, so it cannot be a handoff id"
    # Read to confirm the handoff exists and validates, never to modify it. A transition filed under
    # an id nothing posted is a status for a handoff no reader will ever go looking for.
    record, problem = store.read_json(path(root, handoff_id), SCHEMA)
    if record is None:
        return None, [], problem or f"no handoff with id {handoff_id} under this root"
    # No second `if problem` after that. `read_json`'s contract is that every failure returns a
    # `None` record, so a record in hand means there is no problem to check for, and the check that
    # used to be here was unfalsifiable: mutating it to `if False:` left the suite green, which this
    # repo treats as a defect rather than as coverage.
    seen, problems = transitions(root, handoff_id)
    return seen, problems, None


def _move(root, handoff_id, status, after, by, note, at):
    """Write one move at `after`. Returns `(transition, problem)`.

    The only writer of a transition file, for both verbs. Which fields a move carries and how it
    reaches disk is then one thing rather than two that agree today.
    """
    entry = {"at": at or store.now(), "status": status, "after": after}
    if by:
        entry["by"] = by
    if note:
        entry["note"] = note

    problem = store.create_json(transition_path(root, handoff_id, after), entry, TRANSITION)
    return (None, problem) if problem else (entry, None)


def resolve(root, handoff_id, status, by=None, note=None, at=None):
    """Declare the status of a handoff whose last position is tied. Returns `(transition, problem)`.

    #52. Two disagreeing moves at the *last* position leave no current status to move on from, so
    `set_status` refuses every further move and `list` and `show` exit 1 for good. Reporting the
    disagreement rather than resolving it is right - guessing which of two concurrent moves came
    first is how a closed handoff comes back open - but the state was then unrecoverable through the
    tool, in a repo whose whole argument is that hand-editing the store is how things go wrong.

    Nothing is erased and nothing is decided on anyone's behalf. The tie stays on disk, `_contested`
    goes on reporting it for as long as the handoff exists, and this writes one more move at
    `max + 1` with `by` and `note` recording who resolved it and why, which is what those two fields
    are for. All that changes is that the handoff can move again.

    Refused unless the last position really is tied. Without that check this is `set_status` with
    the already-in-that-status guard taken out, reachable by typo, and the one verb here that
    writes a status nothing derived would also be the easiest one to use by accident.
    """
    seen, problems, refusal = _moving(root, handoff_id, status)
    if refusal:
        return None, refusal
    if problems:
        # Still a refusal, and this is the case it would be tempting to wave through: an unreadable
        # move could be one of the two at the last position, so which statuses are tied cannot be
        # read, and resolving a tie that may not be the tie on disk is exactly the guess this verb
        # exists to avoid making.
        return None, "; ".join(problems)
    if _settled(seen):
        current, _ = _status_of(handoff_id, seen)
        return None, (
            f"{handoff_id} has one status at its last position ({current}), so there is nothing to "
            "resolve; accept or close it"
        )
    return _move(root, handoff_id, status, 1 + max(e["after"] for e in seen), by, note, at)


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
    seen, problems, refusal = _moving(root, handoff_id, status)
    if refusal:
        return None, refusal
    current, faults = _status_of(handoff_id, seen)
    if problems or not _settled(seen):
        # Refusing rather than guessing. An unreadable move could be the latest one, and a
        # contested last position has no latest one, so `current` may not be current - and moving
        # from a status that is not the real one is how a closed handoff comes back open. `resolve`
        # is the way out of the second of those, and it is a separate verb because it writes a
        # status nothing derived.
        return None, "; ".join([*problems, *faults])
    if current == status:
        return None, f"{handoff_id} is already {status}"

    # One past the highest position read, rather than the number of files read. Two writers that
    # read the same state have to land on the same number, because that shared number is the only
    # thing that makes a concurrent pair detectable at all. Counting files breaks it as soon as
    # any position holds two moves: the count stops equalling the position, so two sessions acting
    # on the same status file at different positions and neither one is reported.
    after = (1 + max(entry["after"] for entry in seen)) if seen else 0
    return _move(root, handoff_id, status, after, by, note, at)


def state_of(root, handoff_id):
    """The current status of one handoff, and anything wrong with how it got there.

    Returns `(status, problems)`. No moves at all means `open`: `post` writes none, so an empty
    directory says "never changed since it was posted" and nothing else.

    A problem never suppresses the status. A caller rendering a list must be able to show the row
    *and* the fault, because dropping the row would hide a handoff, which is worse than showing one
    whose state is in question.
    """
    entries, problems = transitions(root, handoff_id)
    status, faults = _status_of(handoff_id, entries)
    return status, problems + faults


def _status_of(handoff_id, entries):
    """The current status of an ordered list of moves, plus a problem per contested position.

    Split out because `set_status` needs this without re-reading the directory it has just read, and
    the two must not be able to disagree about what the current status is.

    Two moves sharing an `after` were written against the same state, so they are concurrent and
    nothing here can say which came first. Two concurrent *identical* moves are not a problem - both
    are true, and the handoff is in that state either way. Two that disagree are reported and not
    resolved, for the same reason the old status-against-history disagreement was.
    """
    if not entries:
        return OPEN, []
    return entries[-1]["status"], _contested(handoff_id, entries)


def _contested(handoff_id, entries):
    """One problem per position whose moves disagree with each other, in position order.

    Every position, not only the last one. The first version compared each move against the last
    move's position, so a disagreement was reported right up until one further move landed after it
    and then it vanished completely: two sessions had moved one handoff two ways and the store had
    nothing left to say about it. A later uncontested move does settle what the status is *now*,
    which is why this returns problems and never touches the status; what it cannot do is make the
    disagreement not have happened.
    """
    first_at, problems = {}, []
    for entry in entries:
        first = first_at.setdefault(entry["after"], entry["status"])
        if first != entry["status"]:
            problems.append(
                f"{handoff_id} has two moves at position {entry['after']} that disagree "
                f"({first!r} and {entry['status']!r}); they were made against the same state, so "
                "which came first cannot be worked out from here"
            )
    return problems


def _settled(entries):
    """Whether the last position holds one status, so there is a current one to move on from.

    A different question from "is anything contested". A disagreement at an earlier position is
    reported, but a later uncontested move settles what the status is now, and refusing to move on
    from it would freeze the handoff for good over a race already superseded, with no verb anywhere
    to unfreeze it. Only a contest at the *last* position leaves no current status to move from.
    """
    if not entries:
        return True
    last = entries[-1]["after"]
    return len({entry["status"] for entry in entries if entry["after"] == last}) == 1


def load_all(root):
    """Every handoff under this root as `(record, status)`, plus problems.

    A pair rather than a `status` key added to the record on the way past. Nothing in memory then
    looks like a field that is on disk, and a caller has to name which half it is reading - which is
    the property this whole module is arranged around.
    """
    found, problems = store.read_each(store.handoffs_dir(root), SCHEMA)
    pairs = []
    for file, record in found:
        # The id inside the file is what finds the moves, so it has to be the name the file was
        # read from. Compared against that name, not stat-ed as `<id>.json`: the first version did
        # the latter, which passes whenever *some* file of that name exists, so swapping two
        # records' ids had each row render the other's status and report nothing at all, and
        # copying one file gave two rows under one id. Two inputs that agree cannot say which one
        # was read.
        if record["id"] != file.stem:
            problems.append(
                f"{store.printable(file.name)} holds the id {record['id']}, so it is not named "
                "after the handoff in it; the moves live under the id, and the status below is not "
                "to be trusted"
            )
        status, faults = state_of(root, record["id"])
        problems += faults
        pairs.append((record, status))
    return pairs, problems


# The two fields #44 removed. `additionalProperties` is false, so the current shape cannot hold
# either one, which makes their presence a positive test for the old shape rather than a guess at
# why a record was refused.
PRE_44_KEYS = ("status", "history")


def unconverted(root):
    """Records written before #44, as problems that say which fix applies. See #51.

    `load_all` already refuses these and names the file and the key, and that refusal is the right
    direction for the breakage to travel: reading the record and ignoring the two fields would
    silently reopen every handoff that was closed under the old shape. What it does not say is that
    there is a conversion at all, so the line reads as a corrupt file and the only action it
    suggests is deleting one - which for a handoff is the loss this plugin exists to stop.

    Keyed on the fields rather than on the validator's message. The message is prose, a schema
    change rewrites it, and a diagnostic that matches on it goes quiet at exactly the moment the
    shape changes again.
    """
    problems = []
    # No schema, deliberately: the whole point is to read a record the current schema refuses.
    found, _ = store.read_each(store.handoffs_dir(root))
    for file, record in found:
        if not isinstance(record, dict):
            continue
        present = [key for key in PRE_44_KEYS if key in record]
        if not present:
            continue
        moves = store.printable(store.transitions_dir(root, file.stem).name)
        problems.append(
            f"{store.printable(file.name)} was written before #44 and still carries "
            f"{', '.join(present)}, so it is refused rather than read. To convert it: drop those "
            "keys from the record, then write "
            f"one file per old history entry into {moves}/, named 0000-<hex>.json upwards, each "
            '{"at": the entry\'s at, "status": its status, "after": its position counting from 0}.'
        )
    return problems


def unresolved(root):
    """Handoffs frozen by a tie at their last position, as problems naming the verb. See #52.

    `_contested` already reports the disagreement itself, and this is a second line about the same
    handoff on purpose: that one says what happened, and until `resolve` existed there was nothing
    anywhere that said what to do about it. Only a tie at the *last* position, because that is the
    only one that stops a handoff moving - an earlier one is reported forever and blocks nothing.
    """
    problems = []
    found, _ = store.read_each(store.handoffs_dir(root), SCHEMA)
    for _, record in found:
        seen, faults = transitions(root, record["id"])
        if faults or _settled(seen):
            continue
        last = seen[-1]["after"]
        tied = sorted({entry["status"] for entry in seen if entry["after"] == last})
        problems.append(
            f"{record['id']} is frozen at position {last}: {' and '.join(tied)} were both moved "
            "against the same state, so it has no current status and no further move is accepted. "
            f"`exchange handoff resolve {record['id']} --status <{'|'.join(STATUSES)}> "
            "--note <why>` writes one at the next position, recording who decided "
            "rather than erasing the tie."
        )
    return problems


def orphan_moves(root):
    """Moves directories with no record beside them, as problems. See #53.

    Nothing iterates directories - `load_all` walks records and asks each one for its moves - so a
    `<id>.d` whose `<id>.json` has gone is read by nothing at all. `rm handoffs/<id>.json` is the
    route in, there being no `handoff delete`, and the dangerous half of it is already closed: #50
    made `post` refuse an id that has moves under it, so a new handoff cannot inherit a stranger's
    status. What is left is that the directory is invisible. It costs that id forever, and the only
    symptom is a refusal message the next time anyone picks the same id, which for a timestamped id
    is never.
    """
    directory = store.handoffs_dir(root)
    found, problems = store.names(directory, "*.d")
    for moves in found:
        if not moves.is_dir():
            continue
        # `<id>.d` back to `<id>` by removing the suffix this layout adds, rather than by `stem`,
        # which would also take a dot inside the id: `note.json.d` is the moves of `note.json`.
        record = directory / f"{moves.name[: -len('.d')]}.json"
        if record.exists():
            continue
        entries, _ = store.names(moves, "*.json")
        # What a reader would have counted, so the same `.tmp-` names `read_each` drops. A count
        # that included one would say the orphan holds a move that nothing was ever going to read,
        # and `litter` reports those on their own line anyway.
        kept = [path for path in entries if not path.name.startswith(store.TMP_PREFIX)]
        problems.append(
            f"{store.printable(moves.name)} holds {len(kept)} move(s) with no "
            f"{store.printable(record.name)} beside it, so nothing "
            "reads it and no handoff can ever be posted under that id again. Either write the "
            "record back or delete the directory."
        )
    return problems


def spelling(scope):
    """One spelling of a root-relative scope, for comparing and nothing else. #62.

    `plugin/lib`, `./plugin/lib`, `plugin/lib/` and `plugin//lib` all pass `store.scope_fault` and
    are one directory, and a matcher comparing them as strings leaves a handoff addressed to a real
    scope unseen by the session claiming it, with nothing on either side looking wrong. Normalised
    here and not on the way in, so a record keeps what its writer typed; `.` comes out as `""`, the
    whole of whatever it is relative to.

    String work, not `pathlib`: resolving asks the filesystem, and a scope names a directory in
    somebody else's checkout as often as in this one. Case is kept, since a case-insensitive
    filesystem is a property of one machine and the two spellings are different paths on another.
    """
    return "/".join(part for part in scope.split("/") if part not in ("", "."))


def _overlaps(one, other):
    """Is either of two spelt paths inside the other, by whole components?"""
    one, other = one.split("/") if one else [], other.split("/") if other else []
    shorter = min(len(one), len(other))
    return one[:shorter] == other[:shorter]


def addressed_to(to, session_id, repos, paths):
    """Is a handoff with this `to` for a session with this id, working in these repos and paths?

    `repos` and `paths` are everything the session has said about where it is, in whatever spelling:
    its claim's lists, plus the repo its cwd is in. Both sides go through `spelling`.

    Paths narrow, in either direction - a session on `plugin` is working on `plugin/lib`, and one on
    `plugin/lib/hook.py` is working inside it. But only against a session that named any: most
    sessions never run `claim --path`, and narrowing them out would hide a handoff from the one
    session in the repo it was for, which is this project's founding failure. Shown to one session
    too many is a row somebody can see is wrong.

    Paths are compared as they stand on each side, both being relative to the repo the handoff
    names, and not qualified by which of a claim's repos they belong to - a claim does not record
    that. So a session in two repos is narrowed by the paths of both.
    """
    if "session_id" in to:
        return to["session_id"] == session_id
    if spelling(to["repo"]) not in {spelling(repo) for repo in repos}:
        return False
    if not to.get("paths") or not paths:
        return True
    return any(
        _overlaps(spelling(wanted), spelling(held)) for wanted in to["paths"] for held in paths
    )


def describe(to, cap):
    """The addressing, in one short phrase, for a human reading a list.

    `cap` is required rather than defaulted, as on the other two renderers here and on
    `claims.describe_focus`. These render text a different session wrote, at whatever width it wrote
    it, and a cap with a default is a cap a future caller forgets to pass and nothing reports. #61
    was filed because the handoff list was the one render in the plugin with no width bound at all,
    and an optional argument is how it would become that again.

    Through `store.printable`, like the two below, and that is why these three live here rather than
    in the caller that prints them. `cli` is in `DECLINED`, on the argument that its output is wrong
    in front of the person who typed the command - which holds for every other line it prints and
    not for these, because the text in them was written by a different session. An escape that
    erases the line makes the output look right, so the person reading it is the last one who would
    notice. A rule whose failure is invisible to the only witness belongs where the sweep can reach
    it. See #47.

    The `session_id` call is a no-op today and is not a guard. What holds that field is the
    `pattern` on `to.oneOf[1].session_id` in the schema, which `store.write_json` applies on the way
    in and `store.read_json` applies again on the way back out, so no value reaching here can
    contain anything the call would remove. Not `store.safe_id`: nothing on this path calls it,
    `to_scope` returning the id unchecked, and the first draft of this paragraph said otherwise -
    which sent a reader to a guard that is not the one doing the work, in the commit about exactly
    that. The pattern is the same text as `store.SAFE_ID` and a separate copy of it, JSON not being
    able to import a Python constant, and nothing asserts the two agree. See #63.

    The mutation table claims no coverage for the call because there is none to claim: replacing it
    with a bare interpolation leaves every check in the suite green. It is here so that the rule is
    "everything in this block goes through the stripper" rather than a per-field judgement that has
    to be re-made correctly each time a schema changes. That is a real choice with a real cost -
    CONTRIBUTING's line about an untestable rule reading as protection applies to it - so the next
    reader should know that the pattern is what holds this field, and relaxing the pattern is not
    made safe by this call.
    """
    if "session_id" in to:
        return store.capped_text(f"session {store.printable(to['session_id'])}", cap)
    paths = to.get("paths")
    repo = store.printable(to["repo"])
    # Capped after joining, so a scope with forty paths in it is bounded by width the way every
    # other line here is. `max_hot_paths` bounds a claim's lists by count; this side has no such
    # setting and does not need one, the question being how much of a terminal one row may take.
    phrase = f"{repo}: {', '.join(store.printable(p) for p in paths)}" if paths else repo
    return store.capped_text(phrase, cap)


def describe_sender(record, cap):
    """Who posted it, in one short phrase.

    `name` is free text in the schema and `cwd` is a filesystem path, so both can hold anything a
    path can hold, which on Linux is everything except `/` and NUL. Neither is the typist's own,
    and neither has a length limit in the schema, which is what `cap` is for.
    """
    return store.capped_text(
        store.printable(record["from"].get("name") or record["from"]["cwd"]), cap
    )


def preview(body, cap):
    """The first line of a body, safe to print and bounded in width.

    `splitlines()[0]` cannot `IndexError` here: `body` has `minLength: 1`, and a string that is only
    a line terminator splits to `['']` rather than `[]`. Checked rather than assumed, because the
    empty-list case would be a crash on a record a sender fully controls.

    One line was the only bound this had, and a line has no length: the body is prose from another
    session with `minLength` and no `maxLength`, so a single-line 23 KB body rendered whole. Same
    row, same size, same defect as the ledger this plugin replaced.
    """
    return store.capped_text(store.printable(body.splitlines()[0]), cap)
