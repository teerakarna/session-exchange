#!/usr/bin/env python3
"""Handoffs: the write path, and the one ambiguity it refuses to resolve.

The first thing in this plugin that writes state a *different* session reads, so the rules in
`handoffs.py` are asserted here by breaking them rather than by describing them:

- Posting never overwrites. An id already on disk is a refusal, because keeping one of two handoffs
  is invisible at both ends - the sender saw it posted, the recipient never had it to miss.
- A status move is its own file and the handoff record never changes, so two sessions moving one
  handoff at the same moment both get their move recorded rather than one of them losing it.
- Order comes from `after`, the number of moves a writer had read, and never from the clock. The
  clock records seconds, and accepting then closing inside one second is ordinary.
- Two moves at the same position that disagree are reported, not resolved. Guessing which came first
  is how a closed handoff comes back open.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import handoffs
import store

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def rooted(tmp):
    """A root with the store laid out, which `post` expects rather than creates."""
    root = pathlib.Path(tmp).resolve()
    store.handoffs_dir(root).mkdir(parents=True)
    return root


print("ids")

check(
    "an id is filename-safe, because it is the filename",
    store.safe_id(handoffs.new_id()) is not None,
    True,
)

# Sortable because the directory listing is the only ordering handoffs have. If a later id sorted
# before an earlier one, `list` would show them out of order with nothing to notice it by.
early = handoffs.new_id("2026-09-01T10:00:00Z")
late = handoffs.new_id("2026-09-01T10:00:01Z")
check("and sorts chronologically, since nothing else orders them", early < late, True)

pair = {handoffs.new_id("2026-09-01T10:00:00Z") for _ in range(2)}
check("two ids in the same second differ, so a collision is a bug not contention", len(pair), 2)

print("addressing")

check(
    "a scope and a session at once is neither, and says so",
    handoffs.to_scope(repo="one", session_id="s")[1] is not None,
    True,
)
check(
    "paths with a session are refused rather than dropped on the way past",
    handoffs.to_scope(session_id="s", paths=["a"]),
    (None, "--path narrows a repo scope, so it cannot go with --session"),
)
check(
    "nothing at all names the flags rather than failing schema validation later",
    handoffs.to_scope()[1],
    "say who it is for: --repo (optionally with --path) or --session",
)
check(
    "paths without a repo says which flag is missing, not which form failed",
    handoffs.to_scope(paths=["a"])[1],
    "--path narrows a repo scope, so it needs --repo as well",
)
check(
    "a repo with repeated paths keeps one of each, in the order given",
    handoffs.to_scope(repo="one", paths=["b", "a", "b"])[0],
    {"repo": "one", "paths": ["b", "a"]},
)
check(
    "a session scope carries only the id", handoffs.to_scope(session_id="s")[0], {"session_id": "s"}
)
check(
    "describe names a narrowed scope",
    handoffs.describe({"repo": "r", "paths": ["a", "b"]}),
    "r: a, b",
)
check("and a session scope reads as one", handoffs.describe({"session_id": "s"}), "session s")

print("posting never overwrites")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    to = {"repo": "repo"}
    # Not the root. The sender's cwd is the only thing identifying a handoff posted from a terminal
    # the registry knows nothing about, and a fixture where the two are the same cannot tell a
    # recorded cwd from a recorded root.
    sender = root / "repo" / "somewhere"

    record, problem = handoffs.post(root, to, "first", sender, handoff_id="fixed-id")
    check(
        "a handoff is written and handed back, and reads as open",
        (problem, handoffs.state_of(root, "fixed-id")),
        (None, ("open", [])),
    )
    # Not a field on the record, and not a first move restating `created` and `open` either. An
    # empty transitions directory is unambiguous: never changed since it was posted.
    check("with no status in it", "status" in record, False)
    check(
        "and no moves beside it either",
        store.transitions_dir(root, "fixed-id").exists(),
        False,
    )

    second, problem = handoffs.post(root, to, "second", sender, handoff_id="fixed-id")
    # `problem or ""` rather than `problem`. When this rule is the one that broke, `problem` is
    # None, and a substring test against None is a TypeError that takes the next twenty checks in
    # this file down with it. A check whose failure mode is a traceback reports one broken rule as
    # a broken file, which is the wrong thing to be told.
    check(
        "the same id again is refused, not replaced",
        (second, "overwrite" in (problem or "")),
        (None, True),
    )
    on_disk = json.loads(handoffs.path(root, "fixed-id").read_text())
    check("and the first body is still the one on disk", on_disk["body"], "first")

    check(
        "an empty body is refused before anything is written",
        handoffs.post(root, to, "   \n", sender)[1],
        "a handoff with no body says nothing; give it one",
    )
    # The message, not just the refusal: the schema rejects this id too, so an assertion on `None`
    # alone passes whether the filename rule ran or the validator caught it on the way out, and only
    # one of those two happens before anything is written.
    check(
        "an id that cannot be a filename is refused as a filename, before the write",
        handoffs.post(root, to, "body", sender, handoff_id="../escape")[1],
        "'../escape' cannot be a filename, so it cannot be a handoff id",
    )
    check("so only the one file exists", len(list(store.handoffs_dir(root).iterdir())), 1)

    record, _ = handoffs.post(root, to, "body", sender, session_id="s1", name="caller")
    # `.get` on the two optional halves, so a missing field is a failed check naming it rather
    # than a KeyError that stops the file.
    check(
        "the sender is recorded whole when it is known",
        (record["from"]["cwd"], record["from"].get("session_id"), record["from"].get("name")),
        (str(sender), "s1", "caller"),
    )
    record, _ = handoffs.post(root, to, "body", sender)
    check(
        "and cwd alone is enough when it is not - the schema asks for no more",
        (record["from"], "session_id" in record["from"]),
        ({"cwd": str(sender)}, False),
    )

    # One timestamp, used twice. The id has to sort where the handoff belongs chronologically, which
    # it only does if both come from the same clock reading rather than two calls to `now()`.
    record, _ = handoffs.post(root, to, "body", sender, at="2026-01-02T03:04:05Z")
    check(
        "the posting time is what is recorded, and what the id is built from",
        (record["created"], record["id"].startswith("20260102T030405Z-")),
        ("2026-01-02T03:04:05Z", True),
    )

print("a status move is its own file, and the record it moves is never touched")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    posted, _ = handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")

    # Both moves are given the same `at` explicitly. Two calls in a row share a second in practice
    # almost always, which is not the same as always: a check that only sometimes exercises the case
    # it is named after passes on the runs where it tested nothing.
    same_second = "2026-01-02T03:04:05Z"
    move, problem = handoffs.set_status(
        root, "h1", handoffs.ACCEPTED, by="me", note="mine now", at=same_second
    )
    check(
        "accepting writes one move, at position zero, and hands it back",
        (problem, move["status"], move["after"]),
        (None, "accepted", 0),
    )
    check(
        "keeping who and why, which is the whole reason the moves are kept at all",
        (move["by"], move["note"]),
        ("me", "mine now"),
    )
    check("and the handoff reads as accepted", handoffs.state_of(root, "h1"), ("accepted", []))
    # The point of the whole shape. The sender wrote this file and nothing else ever writes it, so
    # there is no second copy of the status to contradict the moves and no read-modify-write to lose
    # a concurrent one.
    check(
        "while the record on disk is byte-for-byte what post wrote",
        json.loads(handoffs.path(root, "h1").read_text()),
        posted,
    )

    move, problem = handoffs.set_status(root, "h1", handoffs.CLOSED, at=same_second)
    check("closing adds a second move rather than replacing the first", move["after"], 1)
    check(
        "so both moves are on disk, in order",
        [e["status"] for e in handoffs.transitions(root, "h1")[0]],
        ["accepted", "closed"],
    )
    # The bug that `after` exists for. `store.now()` records seconds, so accepting and then
    # closing inside one second is ordinary, and the first version of this sorted the directory by
    # a name built from that timestamp - which left the order to the random suffix and read a
    # closed handoff back as accepted about half the time.
    check(
        "the clock does not decide the order, and here it cannot: both moves share a second",
        (handoffs.state_of(root, "h1"), {e["at"] for e in handoffs.transitions(root, "h1")[0]}),
        (("closed", []), {same_second}),
    )

    # Not absorbed as a no-op: either the caller is reading a stale render or two sessions are
    # answering the same thing, and a second identical move would hide both.
    move, problem = handoffs.set_status(root, "h1", handoffs.CLOSED)
    check("the status it already has is refused", (move, problem), (None, "h1 is already closed"))
    check("and nothing was written", len(handoffs.transitions(root, "h1")[0]), 2)

    check(
        "a status that is not one of the three is refused before any read",
        handoffs.set_status(root, "h1", "done")[1],
        "'done' is not a handoff status; one of open, accepted, closed",
    )
    # `or ""` for the same reason as the overwrite check above - and this one was missed when
    # that one was fixed. The rules that make this return a problem are the rules a mutation
    # breaks, and a `TypeError` here would stop the file before the ambiguity section runs.
    check(
        "an id with no record is named",
        "no handoff with id h2" in (handoffs.set_status(root, "h2", handoffs.OPEN)[1] or ""),
        True,
    )
    # A move filed under an id nothing posted is a status for a handoff no reader will go looking
    # for. Asserted on the filesystem rather than on the message, because the refusal has to happen
    # before the write, not instead of reporting it.
    check(
        "and nothing was written under it either",
        store.transitions_dir(root, "h2").exists(),
        False,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    # Two names that sort the wrong way round on purpose. The name is there for a human listing the
    # directory; `after` is the ordering, and the two are only kept in step by this module writing
    # both of them. A hand-edited name, or one left by the version that ordered by filename, must
    # not be able to reorder the moves - which is the bug, exactly, restaged as a check.
    moves = store.transitions_dir(root, "h1")
    misnamed = (("0009-aaa", handoffs.ACCEPTED, 0), ("0001-bbb", handoffs.CLOSED, 1))
    for name, status, after in misnamed:
        store.create_json(
            moves / f"{name}.json",
            {"at": store.now(), "status": status, "after": after},
            handoffs.TRANSITION,
        )
    check(
        "the filename does not order the moves; the position their writer recorded does",
        (handoffs.state_of(root, "h1"), [e["status"] for e in handoffs.transitions(root, "h1")[0]]),
        (("closed", []), ["accepted", "closed"]),
    )

print("two moves made against the same state are reported, never resolved")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    handoffs.set_status(root, "h1", handoffs.CLOSED)

    # What two genuinely concurrent sessions produce: both read zero moves, both write position
    # zero, and neither write is lost because neither is a rewrite of the other's file. Forged
    # here because a test cannot race two processes reliably, and the state on disk is the same
    # either way.
    forged = handoffs.transition_path(root, "h1", 0)
    store.create_json(
        forged, {"at": store.now(), "status": handoffs.ACCEPTED, "after": 0}, handoffs.TRANSITION
    )

    status, problems = handoffs.state_of(root, "h1")
    check(
        "state_of names the position and both statuses, so a reader knows what to go and look at",
        (
            len(problems),
            *(s in (problems[0] if problems else "") for s in ("position 0", "'accepted'", "h1")),
        ),
        (1, True, True, True),
    )
    # Still returned alongside the problem. A caller rendering a list has to be able to show the row
    # *and* the fault: dropping it would hide a handoff, which is worse than showing a doubtful one.
    check("while still returning a status", status in handoffs.STATUSES, True)

    stored, problems = handoffs.load_all(root)
    check("load_all reports it and keeps the row", (len(stored), len(problems)), (1, 1))
    check(
        "a move on it is refused rather than filed after a position that has no last entry",
        handoffs.set_status(root, "h1", handoffs.OPEN)[0],
        None,
    )
    check("leaving the two moves as they were found", len(handoffs.transitions(root, "h1")[0]), 2)

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    # Two closes at one position, not two different statuses. Both are true and the handoff is
    # closed either way, so this is the one concurrent case with nothing to report - and it must not
    # be reported, or every ordinary double-close would show a fault.
    handoffs.set_status(root, "h1", handoffs.CLOSED)
    duplicate = handoffs.transition_path(root, "h1", 0)
    store.create_json(
        duplicate, {"at": store.now(), "status": handoffs.CLOSED, "after": 0}, handoffs.TRANSITION
    )
    check(
        "two identical moves at one position agree, so nothing is wrong",
        handoffs.state_of(root, "h1"),
        ("closed", []),
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    record, _ = handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    check(
        "no moves at all is open, with nothing to report",
        handoffs.state_of(root, "h1"),
        ("open", []),
    )
    handoffs.set_status(root, "h1", handoffs.ACCEPTED)
    handoffs.set_status(root, "h1", handoffs.CLOSED)
    stored, problems = handoffs.load_all(root)
    check(
        "and a handoff this module wrote reads back clean, however many times it moved",
        (stored, problems),
        ([(record, "closed")], []),
    )

    # `read_all` hands back contents without filenames, so the id inside the file is what finds the
    # moves. A hand-edited id would look under a directory that does not exist, `state_of` would say
    # open, and a closed handoff would quietly come back.
    path = handoffs.path(root, "h1")
    renamed = json.loads(path.read_text())
    renamed["id"] = "h9"
    path.write_text(json.dumps(renamed))
    stored, problems = handoffs.load_all(root)
    check(
        "an id that does not name its own file is reported, with the row still shown",
        (len(stored), len(problems), "not named after it" in problems[0]),
        (1, 1, True),
    )

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
