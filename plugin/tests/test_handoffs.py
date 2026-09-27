#!/usr/bin/env python3
"""Handoffs: the write path, and the one disagreement it refuses to resolve.

The first thing in this plugin that writes state a *different* session reads, so the two rules in
`handoffs.py` are asserted here by breaking them rather than by describing them:

- Posting never overwrites. An id already on disk is a refusal, because keeping one of two handoffs
  is invisible at both ends - the sender saw it posted, the recipient never had it to miss.
- `status` is derived from `history` in one write, and a record where the two disagree is reported
  rather than repaired. Guessing which half is stale is how a closed handoff comes back open.
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
    check("a handoff is written and handed back", (problem, record["status"]), (None, "open"))
    # A single entry restating `created` and `open` is not a record of anything, and an absent
    # history is unambiguous: never changed since it was posted.
    check("with no history at all", "history" in record, False)

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

print("status moves, in one write, with history as the record")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")

    record, problem = handoffs.set_status(root, "h1", handoffs.ACCEPTED, by="me", note="mine now")
    check(
        "accepting appends one entry and takes the status off it",
        (problem, record["status"], [e["status"] for e in record["history"]]),
        (None, "accepted", ["accepted"]),
    )
    check(
        "keeping who and why, which is the whole reason history exists",
        (record["history"][-1]["by"], record["history"][-1]["note"]),
        ("me", "mine now"),
    )

    record, problem = handoffs.set_status(root, "h1", handoffs.CLOSED)
    check(
        "closing appends rather than rewriting",
        [e["status"] for e in record["history"]],
        ["accepted", "closed"],
    )

    # Not absorbed as a no-op: either the caller is reading a stale render or two sessions are
    # answering the same thing, and a second identical entry would hide both.
    record, problem = handoffs.set_status(root, "h1", handoffs.CLOSED)
    check("the status it already has is refused", (record, problem), (None, "h1 is already closed"))
    on_disk = json.loads(handoffs.path(root, "h1").read_text())
    check("and nothing was appended", len(on_disk["history"]), 2)

    check(
        "a status that is not one of the three is refused before any read",
        handoffs.set_status(root, "h1", "done")[1],
        "'done' is not a handoff status; one of open, accepted, closed",
    )
    check(
        "an id with no record is named",
        "no handoff with id h2" in handoffs.set_status(root, "h2", handoffs.OPEN)[1],
        True,
    )

print("a record whose two halves disagree is reported, never resolved")

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    handoffs.set_status(root, "h1", handoffs.CLOSED)

    path = handoffs.path(root, "h1")
    tampered = json.loads(path.read_text())
    tampered["status"] = handoffs.OPEN
    path.write_text(json.dumps(tampered))

    status, problem = handoffs.state_of(tampered)
    check(
        "state_of names both halves, so a reader knows which file to go and look at",
        (
            problem is not None,
            *(s in (problem or "") for s in ("'open'", "'closed'", "h1")),
        ),
        (True, True, True, True),
    )
    # Still returned alongside the problem. A caller rendering a list has to be able to show the row
    # *and* the fault: dropping it would hide a handoff, which is worse than showing a doubtful one.
    check("while still returning the stated status", status, "open")

    records, problems = handoffs.load_all(root)
    check(
        "load_all reports it and keeps the row",
        (len(records), len(problems)),
        (1, 1),
    )
    check(
        "a move on it is refused rather than appending to a history it cannot vouch for",
        handoffs.set_status(root, "h1", handoffs.ACCEPTED)[0],
        None,
    )
    on_disk = json.loads(path.read_text())
    check("leaving the file exactly as it was found", on_disk, tampered)

with tempfile.TemporaryDirectory() as tmp:
    root = rooted(tmp)
    record, _ = handoffs.post(root, {"repo": "repo"}, "body", root, handoff_id="h1")
    check(
        "no history and a stated status is not a disagreement",
        handoffs.state_of(record),
        ("open", None),
    )
    # Two entries, not one. With a single entry the first and the last are the same object, so a
    # reader comparing `status` against the wrong end of the history agrees with itself.
    handoffs.set_status(root, "h1", handoffs.ACCEPTED)
    handoffs.set_status(root, "h1", handoffs.CLOSED)
    records, problems = handoffs.load_all(root)
    check(
        "and a record this module wrote reads back clean, however long its history",
        (len(records), problems),
        (1, []),
    )

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
