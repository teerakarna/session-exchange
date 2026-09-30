#!/usr/bin/env python3
"""Handoffs: the write path, and the one ambiguity it refuses to resolve.

The first thing in this plugin that writes state a *different* session reads, so the rules in
`handoffs.py` are asserted here by breaking them rather than by describing them:

- Posting never overwrites. An id already on disk is a refusal, because keeping one of two handoffs
  is invisible at both ends - the sender saw it posted, the recipient never had it to miss.
- A status move is its own file and the handoff record never changes, so two sessions moving one
  handoff at the same moment both get their move recorded rather than one of them losing it.
- Order comes from `after`, one past the highest position a writer read, and never from the clock.
  The clock records seconds, and accepting then closing inside one second is ordinary.
- Two moves at the same position that disagree are reported, not resolved, at whatever position they
  sit and not only the newest. Guessing which came first is how a closed handoff comes back open.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import handoffs
import store

failures = []

# Wider than anything the stripping checks render, so those checks say what they say about stripping
# and nothing about width. The cap itself is asserted separately, on its own text.
WIDE = 10_000


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
    handoffs.describe({"repo": "r", "paths": ["a", "b"]}, WIDE),
    "r: a, b",
)
check("and a session scope reads as one", handoffs.describe({"session_id": "s"}, WIDE), "session s")

check(
    "an absolute repo is refused, naming the flag and the shape",
    handoffs.to_scope(repo="/etc")[1],
    "--repo is a relative path, so it cannot start with /: /etc",
)
check(
    "so is one that climbs out, and it is a different message because it is a different mistake",
    handoffs.to_scope(repo="../../../../etc")[1],
    "--repo cannot use .. to climb out: ../../../../etc",
)
check(
    "a .. anywhere in the repo counts, not only at the front",
    handoffs.to_scope(repo="a/../../b")[1],
    "--repo cannot use .. to climb out: a/../../b",
)
# The half a guard written for `repo` alone leaves behind. Separate checks per shape and per field,
# because one check over a loop passes as soon as any element is refused.
check(
    "a path that climbs out is refused too, with a repo that is fine",
    handoffs.to_scope(repo="ok", paths=["../../etc"])[1],
    "--path cannot use .. to climb out: ../../etc",
)
check(
    "and an absolute one",
    handoffs.to_scope(repo="ok", paths=["/etc"])[1],
    "--path is a relative path, so it cannot start with /: /etc",
)
check(
    "a later path is reached, so the loop does not stop at the first element",
    handoffs.to_scope(repo="ok", paths=["fine", "also/fine", "../out"])[1],
    "--path cannot use .. to climb out: ../out",
)
check(
    "a refused scope returns no scope, so a caller ignoring the problem writes nothing",
    handoffs.to_scope(repo="/etc")[0],
    None,
)
# The shape that only becomes one of the two above once something renders it. `\t/etc` does not
# start with `/`, so the first check in this block passes it, and then every renderer here shows
# `/etc`.
check(
    "a repo that merely renders as an absolute path is refused as well",
    handoffs.to_scope(repo="\t/etc")[1],
    "--repo cannot hold characters a terminal does not show: U+0009. "
    "Without them it reads as '/etc'",
)
check(
    "and so is a path, the two fields being constrained identically",
    handoffs.to_scope(repo="ok", paths=["fine", "p\033[2Kq"])[1],
    "--path cannot hold characters a terminal does not show: U+001B. "
    "Without them it reads as 'p[2Kq'",
)
# `..` as a component, not as a substring. These are ordinary names and refusing them would be the
# guard being wrong in the direction nobody reports, because the handoff just never posts.
check("a name containing dots is not a climb", handoffs.to_scope(repo="a..b/..bashrc")[1], None)
check(
    "and that scope is the one that was asked for",
    handoffs.to_scope(repo="a..b/..bashrc")[0],
    {"repo": "a..b/..bashrc"},
)

print("another session's text, on its way to a terminal")

check(
    "describe strips an escape out of a repo, which the schema still allows through",
    handoffs.describe({"repo": "r\033[2K", "paths": ["p\rq"]}, WIDE),
    "r[2K: pq",
)
check(
    "a sender's name is not the typist's, so it is stripped as well",
    handoffs.describe_sender({"from": {"name": "peer\033[1;31m", "cwd": "/tmp"}}, WIDE),
    "peer[1;31m",
)
check(
    "and the cwd it falls back to, which is a path and can hold anything a path can",
    handoffs.describe_sender({"from": {"cwd": "/tmp/w\007d"}}, WIDE),
    "/tmp/wd",
)
check(
    "a body preview is one line, stripped",
    handoffs.preview("first\033[2K line\nsecond line", WIDE),
    "first[2K line",
)
# Checked rather than assumed, because the empty-list case would be a crash on a record whose
# content the sender chooses. `minLength: 1` makes "" unreachable from disk; a lone terminator is
# not unreachable, and it is the one that splits to [''] rather than [].
check(
    "a body that is only a newline previews as empty, not as a crash",
    handoffs.preview("\n", WIDE),
    "",
)

# #61. One line was the only bound these had, and a line has no length: `body` has `minLength` and
# no `maxLength`, so a single-line 23 KB body rendered whole into whoever's terminal listed it. Each
# of the three renderers separately, because a cap applied to two of them reads as done.
check(
    "a long body preview is cut at the cap, with the rest counted",
    handoffs.preview("b" * 300, 240),
    "b" * 240 + " +60 more chars",
)
check(
    "a scope with more paths than fit is bounded too, being joined before it is capped",
    handoffs.describe({"repo": "r", "paths": ["p" * 40] * 10}, 60),
    f"r: {'p' * 40}, {'p' * 15} +361 more chars",
)
check(
    "a session scope as well, that being the branch which returns before the other one",
    handoffs.describe({"session_id": "s" * 40}, 12),
    "session ssss +36 more chars",
)
check(
    "and a sender, whose name and cwd both have a length nothing constrains",
    handoffs.describe_sender({"from": {"cwd": "/tmp/" + "d" * 300}}, 20),
    "/tmp/ddddddddddddddd +285 more chars",
)

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
    # The write is checked, and so is the count. Without both, this check passes with one move on
    # disk, because one close also reads back as `("closed", [])` - it would be named after the
    # concurrent case and never exercise it.
    check(
        "a second move at a position that already holds one is written, not refused",
        store.create_json(
            duplicate,
            {"at": store.now(), "status": handoffs.CLOSED, "after": 0},
            handoffs.TRANSITION,
        ),
        None,
    )
    check("so there are two of them", len(handoffs.transitions(root, "h1")[0]), 2)
    check(
        "two identical moves at one position agree, so nothing is wrong",
        handoffs.state_of(root, "h1"),
        ("closed", []),
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    # A contested position with a later move sitting on top of it. The first version compared every
    # move against the *last* move's position, so this disagreement was reported while it was the
    # newest thing on disk and then vanished the moment anything landed after it: two sessions had
    # moved one handoff two ways and `list` went back to showing a row with nothing beside it.
    moves = store.transitions_dir(root, "h1")
    buried = (
        ("0000-aaa", handoffs.ACCEPTED, 0),
        ("0000-bbb", handoffs.CLOSED, 0),
        ("0001-ccc", handoffs.OPEN, 1),
    )
    for name, status, after in buried:
        store.create_json(
            moves / f"{name}.json",
            {"at": store.now(), "status": status, "after": after},
            handoffs.TRANSITION,
        )
    status, problems = handoffs.state_of(root, "h1")
    check(
        "a disagreement is still reported once a later move has settled the status",
        (status, len(problems), "position 0" in (problems[0] if problems else "")),
        ("open", 1, True),
    )
    # And it does not freeze the handoff. The last position holds one move, so the current status is
    # knowable, and refusing to move on from it would strand the handoff for good over a race that
    # has already been superseded - with no verb anywhere to unstrand it.
    check(
        "while a settled last position can still be moved on from",
        handoffs.set_status(root, "h1", handoffs.CLOSED)[1],
        None,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    # Two concurrent accepts at position 0 - the blessed case, both true, nothing to report. What
    # is under test is the number the *next* writer picks. Counting the files read gives 2 here,
    # while a session that had read only one of the two would give 1, so two writers acting on the
    # same status would file at different positions and neither would ever be seen as concurrent.
    # One past the highest position read gives both of them 1, which is what makes the tie
    # detectable.
    handoffs.set_status(root, "h1", handoffs.ACCEPTED)
    store.create_json(
        handoffs.transition_path(root, "h1", 0),
        {"at": store.now(), "status": handoffs.ACCEPTED, "after": 0},
        handoffs.TRANSITION,
    )
    move, _ = handoffs.set_status(root, "h1", handoffs.CLOSED)
    check(
        "a move files one past the highest position read, not the number of moves read",
        (move["after"], len(handoffs.transitions(root, "h1")[0])),
        (1, 3),
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    handoffs.set_status(root, "h1", handoffs.ACCEPTED)
    # A move that will not parse. It could be the latest one, so the status in hand may not be the
    # current one, and a move computed from it could take a closed handoff back to open. Nothing in
    # this module writes a file like this, which is why it has to be forged - and until it was, both
    # the refusal and the reporting were unfalsifiable: a mutation dropping the unreadable half of
    # the guard left the whole suite green.
    (store.transitions_dir(root, "h1") / "0001-bad.json").write_text("{ truncated")
    status, problems = handoffs.state_of(root, "h1")
    check(
        "an unreadable move is reported, and the status still comes back",
        (status, len(problems)),
        ("accepted", 1),
    )
    # Named for the handoff, not only for the file. A move file carries no id and its name is a
    # position, so `0001-bad.json could not be read` points at nothing anyone can go and look at,
    # and two handoffs with one bad move each would produce two identical lines.
    check(
        "and the problem names the handoff it belongs to",
        problems[0].startswith("h1: 0001-bad.json") if problems else False,
        True,
    )
    check(
        "a further move is refused rather than computed from the moves that did read",
        handoffs.set_status(root, "h1", handoffs.CLOSED),
        (None, problems[0] if problems else ""),
    )
    check(
        "leaving what was there alone",
        len(list(store.transitions_dir(root, "h1").glob("*.json"))),
        2,
    )

print("a tie at the last position is declared, not erased")


def frozen(root, handoff_id="h1"):
    """A handoff with two disagreeing moves at its last position, which nothing can move on from."""
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id=handoff_id)
    handoffs.set_status(root, handoff_id, handoffs.CLOSED)
    store.create_json(
        handoffs.transition_path(root, handoff_id, 0),
        {"at": store.now(), "status": handoffs.ACCEPTED, "after": 0},
        handoffs.TRANSITION,
    )


with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    frozen(root)
    # The state #52 was filed about: honest, permanent, and with no verb anywhere that answered it.
    check(
        "the ordinary verbs still refuse it, which is what resolve is for",
        handoffs.set_status(root, "h1", handoffs.CLOSED)[0],
        None,
    )

    move, problem = handoffs.resolve(root, "h1", handoffs.CLOSED, by="me", note="both of us closed")
    # Read through a `or {}` rather than straight off `move`, so a resolve that refuses this fails
    # the check by name instead of killing the file on a subscript and reporting nothing at all.
    written = move or {}
    check(
        "resolve writes one more move at the next position, saying who and why",
        (
            problem,
            written.get("after"),
            written.get("status"),
            written.get("by"),
            written.get("note"),
        ),
        (None, 1, "closed", "me", "both of us closed"),
    )
    status, problems = handoffs.state_of(root, "h1")
    # The tie is still on disk and still reported. A verb that made the disagreement go away would
    # be the lost update this whole layout exists to prevent, arriving as a feature.
    check(
        "the tie stays reported, and the handoff has a status again",
        (status, len(problems), "position 0" in (problems[0] if problems else "")),
        ("closed", 1, True),
    )
    check("and the two moves are both still there", len(handoffs.transitions(root, "h1")[0]), 3)
    check(
        "so the everyday verbs work on it again",
        handoffs.set_status(root, "h1", handoffs.OPEN)[1],
        None,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    handoffs.set_status(root, "h1", handoffs.ACCEPTED)
    # Refused on a handoff that is not frozen, and this is the check that matters most: without it
    # `resolve` is `set_status` with the already-in-that-status guard taken out, so the one verb
    # that writes a status nothing derived would also be the one reachable by typo. The moved-once
    # handoff goes first because a never-moved one has no position to write past, so a resolve that
    # stopped refusing would die on that rather than fail a check here and name the rule it broke.
    settled = handoffs.resolve(root, "h1", handoffs.CLOSED, note="why not")
    check(
        "a handoff with nothing wrong with it is refused, and told which verbs to use",
        (
            settled[0],
            "nothing to resolve" in (settled[1] or ""),
            "accept or close" in (settled[1] or ""),
        ),
        (None, True, True),
    )
    check("and nothing was written", len(handoffs.transitions(root, "h1")[0]), 1)
    check(
        "the refusal names the status it does have, so the reader knows where it stands",
        "(accepted)" in (settled[1] or ""),
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    check(
        "a handoff nobody has moved yet is refused as well, being open rather than stuck",
        "(open)" in (handoffs.resolve(root, "h1", handoffs.CLOSED, note="why not")[1] or ""),
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    frozen(root)
    # An unreadable move on a frozen handoff. Which two statuses are tied cannot be read, so the tie
    # being resolved may not be the tie on disk - the one guess this verb exists to avoid making.
    (store.transitions_dir(root, "h1") / "0000-bad.json").write_text("{ truncated")
    refused = handoffs.resolve(root, "h1", handoffs.CLOSED, note="reading past it")
    check(
        "a tie with an unreadable move beside it is still refused",
        (refused[0], "could not be read" in (refused[1] or "")),
        (None, True),
    )
    check(
        "leaving the directory as it was",
        len(list(store.transitions_dir(root, "h1").glob("*.json"))),
        3,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    frozen(root)
    # The three refusals `resolve` shares with `set_status`, which is why they are one function: a
    # second copy would be three rules with only one of them swept.
    check(
        "an unknown status is refused",
        handoffs.resolve(root, "h1", "finished", note="w")[0],
        None,
    )
    check(
        "so is an id that cannot be a filename",
        handoffs.resolve(root, "../h1", handoffs.CLOSED, note="w")[0],
        None,
    )
    check(
        "and an id nothing posted",
        handoffs.resolve(root, "h2", handoffs.CLOSED, note="w")[1],
        "no handoff with id h2 under this root",
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    frozen(root)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h2")
    handoffs.set_status(root, "h2", handoffs.CLOSED)
    reported = handoffs.unresolved(root)
    check(
        "only the frozen one is listed, and it names the verb and the flags",
        (
            len(reported),
            reported[0].startswith("h1 is frozen at position 0") if reported else False,
            "exchange handoff resolve h1" in (reported[0] if reported else ""),
            "--note" in (reported[0] if reported else ""),
        ),
        (1, True, True, True),
    )
    check(
        "and both of the statuses that are tied, so nobody has to go and read the files",
        ("accepted and closed" in reported[0]) if reported else False,
        True,
    )
    handoffs.resolve(root, "h1", handoffs.CLOSED, note="decided")
    check("once resolved, it is not reported as frozen again", handoffs.unresolved(root), [])

print("a moves directory is a name in its own right")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    handoffs.set_status(root, "h1", handoffs.CLOSED)
    # A moves directory outliving its record. `rm handoffs/<id>.json` does it, and nothing iterates
    # directories, so what is left is invisible: `load_all` reads records and finds none.
    handoffs.path(root, "h1").unlink()
    check("an orphaned moves directory is read by nothing", handoffs.load_all(root), ([], []))
    # Posting into it would hand a brand-new handoff the old one's status the moment it was
    # written - posted, exit 0, and it reads as closed - so a taken moves directory is a refusal
    # in the same way a taken record is.
    fresh, problem = handoffs.post(root, {"repo": "repo"}, "fresh", root, handoff_id="h1")
    check(
        "and posting over one is refused rather than inheriting its status",
        (fresh, "already has moves" in (problem or "")),
        (None, True),
    )

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    # An id with a dot in it, which `SAFE_ID` allows and `new_id` never produces - but
    # `handoff_id` is an argument, and the ledger importer is its declared next caller. The moves
    # directory was first named after the bare id, so this id put a directory called `note.json`
    # exactly where a record of the id `note` goes: every read reported "Is a directory" for good,
    # and posting `note` was refused for colliding with a name nobody had written. `.d` cannot be
    # a record's name, so the two namespaces cannot overlap whatever the id is.
    _, problem = handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="note.json")
    handoffs.set_status(root, "note.json", handoffs.ACCEPTED)
    check(
        "an id ending in .json keeps its moves out of the records",
        (problem, handoffs.load_all(root)[1], handoffs.state_of(root, "note.json")),
        (None, [], ("accepted", [])),
    )
    check(
        "and leaves the record of a plainer id free to be posted",
        handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="note")[1],
        None,
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

    # The id inside the file is what finds the moves, so it has to be the name the file was read
    # from. A hand-edited id looks under a directory that does not exist, `state_of` says open,
    # and a closed handoff quietly comes back.
    path = handoffs.path(root, "h1")
    renamed = json.loads(path.read_text())
    renamed["id"] = "h9"
    path.write_text(json.dumps(renamed))
    stored, problems = handoffs.load_all(root)
    # `problems[0] if problems else ""` rather than `problems[0]`, for the same reason the `or ""`
    # above exists: when this is the rule that broke there is no problem to index, and an IndexError
    # reports one broken rule as a broken file.
    check(
        "an id that does not name its own file is reported, with the row still shown",
        (len(stored), len(problems), "not named after" in (problems[0] if problems else "")),
        (1, 1, True),
    )

    # The other half of the same rule, and the half a stat cannot see. Copying a record leaves two
    # files whose ids are both real, so `<id>.json is a file` passes for both - and there is no way
    # to tell which of the two the row on screen came out of. Two inputs that agree cannot say which
    # one was read, which is this repo's recurring shape.
    path.write_text(json.dumps(dict(json.loads(path.read_text()), id="h1")))
    (store.handoffs_dir(root) / "h1-copy.json").write_text(path.read_text())
    stored, problems = handoffs.load_all(root)
    check(
        "and so is a second file holding an id that already names one",
        (len(stored), len(problems), "h1-copy.json" in (problems[0] if problems else "")),
        (2, 1, True),
    )

print("a handoff filename in a problem line, which nothing this plugin wrote (#60)")
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    _, problem = handoffs.post(root, {"repo": "r"}, "b", str(root), handoff_id="h1")
    assert problem is None, problem
    folder = store.handoffs_dir(root)
    (folder / "h1.json").rename(folder / "h1\033[2K.json")
    _, found = handoffs.load_all(root)
    misnamed = [p for p in found if "holds the id h1" in p]
    check(
        "a record not named after its id is named stripped, where the session start sees it",
        [("\033" in p, p.startswith("h1[2K.json ")) for p in misnamed],
        [(False, True)],
    )

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    folder = store.handoffs_dir(root)
    folder.mkdir(parents=True)
    (folder / "h2\033[2K.json").write_text(json.dumps({"id": "h2", "status": "open"}))
    found = handoffs.unconverted(root)
    check(
        "a pre-#44 record is named stripped, and so is the directory it is told to write into",
        [("\033" in p, p.startswith("h2[2K.json "), "into h2[2K.d/" in p) for p in found],
        [(False, True, True)],
    )

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    (store.handoffs_dir(root) / "o\033[2K.d").mkdir(parents=True)
    found = handoffs.orphan_moves(root)
    check(
        "an orphaned moves directory is named stripped, and so is the record it is missing",
        [("\033" in p, p.startswith("o[2K.d "), "no o[2K.json beside" in p) for p in found],
        [(False, True, True)],
    )

print("matching a handoff to a session")

# #62, one check per spelling rather than one per branch: every one of these passes `scope_fault`,
# and a matcher comparing them as strings misses the session claiming the same directory.
for written in ("plugin/lib", "./plugin/lib", "plugin/lib/", "plugin//lib", "./plugin/./lib/"):
    check(f"{written!r} is spelt plugin/lib", handoffs.spelling(written), "plugin/lib")
check("'.' is the whole of what it is relative to", handoffs.spelling("."), "")
check("case is kept", handoffs.spelling("Plugin/Lib"), "Plugin/Lib")
check("a leading-dot name is not a '.' component", handoffs.spelling(".github/x"), ".github/x")

to = {"repo": "./repo-one/", "paths": ["plugin//lib"]}
check(
    "the repo is compared by spelling on both sides",
    handoffs.addressed_to({"repo": "repo-one/"}, "s", ["./repo-one"], []),
    True,
)
check(
    "a different repo is not the same one",
    handoffs.addressed_to({"repo": "repo-one"}, "s", ["repo-two"], []),
    False,
)
check(
    "nor is a repo whose name only starts the same",
    handoffs.addressed_to({"repo": "repo"}, "s", ["repo-one"], []),
    False,
)
check(
    "a path inside the one addressed is working on it",
    handoffs.addressed_to(to, "s", ["repo-one"], ["plugin/lib/hook.py"]),
    True,
)
check(
    "and so is a path that contains it",
    handoffs.addressed_to(to, "s", ["repo-one"], ["./plugin"]),
    True,
)
check(
    "a sibling is not, even one sharing a prefix of characters",
    handoffs.addressed_to(to, "s", ["repo-one"], ["plugin/lib2", "docs"]),
    False,
)
check(
    "any one overlapping path of several is enough",
    handoffs.addressed_to(to, "s", ["repo-one"], ["docs", "plugin/lib/x"]),
    True,
)
check(
    "a session that named no paths is not narrowed out of its repo",
    handoffs.addressed_to(to, "s", ["repo-one"], []),
    True,
)
check(
    "nor is anyone by a handoff that named none",
    handoffs.addressed_to({"repo": "repo-one"}, "s", ["repo-one"], ["docs"]),
    True,
)
check(
    "a session on '.' is working on every path in its repo",
    handoffs.addressed_to(to, "s", ["repo-one"], ["./"]),
    True,
)
check(
    "and a handoff for '.' is for every path in it",
    handoffs.addressed_to({"repo": "repo-one", "paths": ["."]}, "s", ["repo-one"], ["docs"]),
    True,
)
check(
    "paths do not reach a session in another repo",
    handoffs.addressed_to(to, "s", ["repo-two"], ["plugin/lib"]),
    False,
)
check(
    "a session-addressed handoff reaches that session",
    handoffs.addressed_to({"session_id": "s"}, "s", [], []),
    True,
)
check(
    "and no other, whatever scope it is in",
    handoffs.addressed_to({"session_id": "s"}, "t", ["repo-one"], ["plugin"]),
    False,
)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
