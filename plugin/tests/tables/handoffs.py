"""The rules `handoffs.py` has to keep, one broken way each."""

from .shape import Mutation

# The first module that writes state a *different* session reads. A claim is written and read by
# one session, so a wrong claim misinforms nobody but its author. A handoff is addressed to
# whoever works in a scope next, which may be a session that does not exist yet. That is why there
# is a table here rather than an entry in `DECLINED` next to `cli`: the argument there is that a
# wrong answer lands in front of the person who typed the command, and here it does not. Nobody is
# watching when a handoff is dropped, because the sender saw it posted and the recipient never had
# it to miss.
#
# Two rules carry the module and most of the table is about them: posting never overwrites, and
# status is read off the moves rather than stored anywhere. The second used to be "`status` is
# derived from `history` in one write", which was the same rule with a field still in it, and #50
# removed the field: a record and a status that has to agree with it is two inputs that agree and
# cannot say which one was read, which is this repo's recurring defect. Now there is one input. The
# mutations that matter most are still the ones that would let a second copy back in.
MUTATIONS = [
    Mutation(
        module="handoffs",
        rule="the timestamp's separators are stripped, because the id is also the filename",
        old='    stamp = (at or store.now()).replace("-", "").replace(":", "")',
        new="    stamp = at or store.now()",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="the id is built from the posting time, so a lexical sort is a chronological one",
        old='    stamp = (at or store.now()).replace("-", "").replace(":", "")',
        new='    stamp = store.now().replace("-", "").replace(":", "")',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Without it, two handoffs posted in the same second collide as a matter of course, and then
        # the only safe behaviour is to retry - which turns a real duplicate into a second row
        # nobody compares. The suffix is what makes a collision a bug rather than contention.
        rule="the random suffix is really there, and long enough to be one",
        old="SUFFIX_BYTES = 3",
        new="SUFFIX_BYTES = 0",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a scope and a session at once is neither",
        old="    if repo and session_id:",
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="repeated paths are deduplicated",
        old='            scope["paths"] = list(dict.fromkeys(paths))',
        new='            scope["paths"] = list(paths)',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # `dict.fromkeys` rather than `set`, and the order is the reason: the paths are rendered
        # back to a human in the order they were typed.
        rule="and the order they were given in survives the deduplication",
        old='            scope["paths"] = list(dict.fromkeys(paths))',
        new='            scope["paths"] = sorted(set(paths))',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The schema's `oneOf` catches an empty `to` on the way to disk, with "does not match any of
        # the allowed forms", which is true and says nothing about which flag was forgotten.
        rule="--path without --repo names the missing flag rather than the failing form",
        old='        return None, "--path narrows a repo scope, so it needs --repo as well"',
        new='        return {"paths": list(paths)}, None',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The mutation is the bug that was there. `to_scope` returned on `session_id` before
        # the paths-without-repo refusal below it, so `--session` with `--path` posted, exited
        # 0, and left the narrowing out of the record. Nothing in the table covered the
        # combination, so the sweep was green on it - which is why this is a table entry and
        # not only a check.
        rule="--path with --session is refused rather than silently dropped",
        old="""        if paths:
            return None, "--path narrows a repo scope, so it cannot go with --session"
        return {"session_id": session_id}, None""",
        new='        return {"session_id": session_id}, None',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="no addressing at all is a refusal, not an empty scope",
        old='    return None, "say who it is for: --repo (optionally with --path) or --session"',
        new="    return {}, None",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a body of nothing but whitespace says nothing",
        old='    if not (body or "").strip():',
        new='    if not (body or ""):',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The filename rule runs before the write, the schema runs during it. Both refuse this id,
        # so only the message says which one ran, and only one of them leaves the directory alone.
        rule="an id that cannot be a filename is caught here, not by the validator",
        old="    handoff_id = handoff_id or new_id(at)\n    if store.safe_id(handoff_id) is None:",
        new="    handoff_id = handoff_id or new_id(at)\n    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The headline rule. An id collision means two handoffs, and keeping one of them is
        # invisible at both ends: no later command's output looks wrong. The mutation is the version
        # that was here until #44: a writer that replaces, guarded by an `exists()` check above it.
        rule="posting never overwrites an id that is already on disk",
        old="    problem = store.create_json(path(root, handoff_id), record, SCHEMA)",
        new="    problem = store.write_json(path(root, handoff_id), record, SCHEMA)",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="one clock reading is used for both the id and the recorded time",
        old="    at = at or store.now()",
        new="    at = store.now()",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="the sender's cwd is recorded, which is all there is when the registry has no row",
        old='        "from": {"cwd": str(cwd)},',
        new='        "from": {"cwd": str(root)},',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="the session id and the display name are not each other",
        old='        record["from"]["session_id"] = session_id',
        new='        record["from"]["name"] = session_id',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The regression guard for the bug this whole shape was rewritten around. The first version
        # of #44 sorted these by filename, the filename began with the timestamp, and `store.now()`
        # records seconds - so accepting and closing inside one second left the order to the random
        # suffix. The name is legibility now; `after` is the ordering.
        rule="moves are ordered by the position their writer recorded, never by their filename",
        old='    return sorted(entries, key=lambda entry: entry["after"]), faults',
        new="    return entries, faults",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # A move file carries no id on purpose - a second copy of it could disagree with the first -
        # and its name is a position, so `0001-a3f2.json could not be read` on its own names nothing
        # anyone can act on, and two handoffs with one bad move each produce two identical lines.
        rule="a problem with a move names the handoff the move belongs to",
        old='    faults = [f"{handoff_id}: {problem}" for problem in problems]',
        new="    faults = list(problems)",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a status that is not one of the three is refused before anything is read",
        old="    if status not in STATUSES:",
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="an id with no record on disk is named as missing",
        old="    if record is None:",
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # One rule per entry, because the first version of this covered both halves of the guard
        # with a single `if False:` - and patching out only the unreadable half left the whole
        # suite green, because nothing in the repo wrote a malformed move file at all. An entry
        # that passes on the strength of the half that is covered is the thing this table exists
        # to prevent.
        rule="a move computed from a move that could not be read is refused",
        old="    if problems or not _settled(seen):",
        new="    if not _settled(seen):",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # A contested last position has no latest entry, so `current` is one of two answers and
        # moving on from the wrong one is how a closed handoff comes back open.
        rule="a move computed from a contested last position is refused",
        old="    if problems or not _settled(seen):",
        new="    if problems:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The other side of it. A disagreement at an earlier position is reported but must not
        # block: a later uncontested move settles what the status is now, and refusing anyway
        # would strand the handoff for good over a race already superseded, with no verb to
        # unstrand it.
        rule="only the last position being contested blocks a move, not any position",
        old='    last = entries[-1]["after"]\n    return len({entry["status"]',
        new='    last = entries[0]["after"]\n    return len({entry["status"]',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # `post` writes no moves, so a handoff that has never been touched has an empty directory
        # and has to be movable. Refusing there would make every first accept fail.
        rule="a handoff with no moves yet is settled, so it can be moved",
        old="    if not entries:\n        return True",
        new="    if not entries:\n        return False",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Not a no-op worth absorbing: either the caller is reading a stale render or two sessions
        # are answering the same thing, and a second identical entry would hide both.
        rule="a move to the status it already has is refused",
        old="    if current == status:",
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="the move records the status moved to, not the one left behind",
        old='    entry = {"at": at or store.now(), "status": status, "after": after}',
        new='    entry = {"at": at or store.now(), "status": current, "after": after}',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Pinned to zero, every move claims to have been made against a fresh handoff, so the second
        # one reads as concurrent with the first and an ordinary sequence reports as contested.
        rule="a move records the position it was made at, so the next one sorts after it",
        old='    after = (1 + max(entry["after"] for entry in seen)) if seen else 0',
        new="    after = 0",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The mutation is what was here first, and the bug is subtle: the count equals the
        # position only while every position holds one move, and the case where it does not is
        # exactly a concurrent pair. Two writers acting on the same status then file at different
        # positions, so the tie the whole layout exists to surface is never detected.
        rule="the position is one past the highest one read, not the number of moves read",
        old='    after = (1 + max(entry["after"] for entry in seen)) if seen else 0',
        new="    after = len(seen)",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # What makes two concurrent writers at one position two files rather than one refusing. The
        # `SUFFIX_BYTES` entry above covers `new_id`, and the id test catches it first, so this half
        # was going unexercised.
        rule="a move's filename carries a random suffix, so two at one position do not collide",
        old='    name = f"{after:04d}-{secrets.token_hex(SUFFIX_BYTES)}.json"',
        new='    name = f"{after:04d}.json"',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="who made the move is kept, which is most of what the moves are for",
        old='        entry["by"] = by',
        new='        entry["note"] = by',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Two kinds of fault reach a reader through here and each gets its own entry, because one
        # `if False:` over both would pass on the strength of whichever half happened to be covered.
        rule="a move that could not be read is reported to whoever asked for the status",
        old="    return status, problems + faults",
        new="    return status, faults",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so is a position whose moves disagree",
        old="    return status, problems + faults",
        new="    return status, problems",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # `post` writes no move, so an empty directory means "never changed since it was posted".
        # Without the guard the next line indexes an empty list, which is the same defect arriving
        # as a traceback.
        rule="no moves at all is open",
        old="    if not entries:\n        return OPEN, []",
        new="    if False:\n        return OPEN, []",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="the current status is the last move, not the first",
        old='    return entries[-1]["status"], _contested(handoff_id, entries)',
        new='    return entries[0]["status"], _contested(handoff_id, entries)',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Dropping the row would hide a handoff, which is worse than showing one whose state is in
        # question. A caller rendering a list has to be able to show the row *and* the fault.
        rule="the status is still returned alongside the problem",
        old='    return entries[-1]["status"], _contested(handoff_id, entries)',
        new="    return None, _contested(handoff_id, entries)",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Without grouping by position every ordinary sequence is a disagreement: accepted then
        # closed are two different statuses, and they were made one after the other.
        rule="only moves at the same position are concurrent",
        old='        first = first_at.setdefault(entry["after"], entry["status"])',
        new='        first = first_at.setdefault(0, entry["status"])',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Every position, not only the newest. The first version compared each move against the last
        # move's position, so a disagreement was reported until one further move landed on top of it
        # and then vanished entirely - two sessions had moved one handoff two ways and the store had
        # nothing left to say about it.
        rule="a disagreement at any position is reported, not only one at the newest",
        old="    for entry in entries:\n        first = first_at.setdefault",
        new="    for entry in entries[-1:]:\n        first = first_at.setdefault",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # Two concurrent *identical* moves are both true and the handoff is in that state either
        # way. Without the comparison the first move at every position disagrees with itself.
        rule="two moves at one position that agree are not a disagreement",
        old='        if first != entry["status"]:',
        new="        if True:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="two moves at one position that disagree are reported",
        old='        if first != entry["status"]:',
        new="        if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # The id inside the file is what finds the moves, so it has to be the name the file came out
        # of. The mutation this replaces stat-ed `<id>.json` instead, which passes whenever *some*
        # file of that name exists: swapping two records' ids had each row render the other's status
        # and report nothing, and copying one file gave two rows under one id.
        rule="the id in a handoff file has to name the file it was read from",
        old='        if record["id"] != file.stem:',
        new="        if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        # A moves directory outlives its record if anyone removes `<id>.json`, and nothing iterates
        # directories, so it is invisible until an id lands on it again. Posting into it hands a
        # brand-new handoff the old one's status: posted, exit 0, and it reads as closed.
        rule="posting never inherits moves already recorded under the id",
        old="    if store.transitions_dir(root, handoff_id).exists():",
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="load_all reports what the moves said rather than only the parse failures",
        old="        problems += faults",
        new="        pass",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and keeps the record it is complaining about",
        old="    return pairs, problems",
        new="    return [], problems",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a narrowed scope is described with the paths that narrow it",
        old=(
            "    return f\"{repo}: {', '.join(store.printable(p) for p in paths)}\" "
            "if paths else repo"
        ),
        new="    return repo",
        caught_by="test_handoffs.py",
    ),
    # #46. Two shapes, two mutations, because one guard covering both would pass on either half and
    # the messages are deliberately different. The third is the `paths` loop, which is the half a
    # guard written for `repo` alone leaves behind - and note it is a separate entry from the two
    # above it rather than a variation of them: what it breaks is the iteration, not the test.
    Mutation(
        module="handoffs",
        rule="a scope path cannot be absolute, because the field is relative to the root",
        old='    if value.startswith("/"):',
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and cannot climb out of the root with ..",
        old='    if ".." in value.split("/"):',
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="every path is checked, not the first one",
        old="            for path in paths:",
        new="            for path in paths[:1]:",
        caught_by="test_handoffs.py",
    ),
    # #47. One per field. The reason is the lesson from #44's review: a single check over three
    # fields passes as soon as one of them is sanitised, so the two that are not have no check at
    # all. Three fields reach the terminal on that block, and the issue said one.
    Mutation(
        module="handoffs",
        rule="a repo reaching a terminal goes through the stripper, the schema having allowed it",
        old='    repo = store.printable(to["repo"])',
        new='    repo = to["repo"]',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="so does the sender, whose name is free text and whose cwd is a path",
        old='    return store.printable(record["from"].get("name") or record["from"]["cwd"])',
        new='    return record["from"].get("name") or record["from"]["cwd"]',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and the body preview, which is the field the issue was filed about",
        old="    return store.printable(body.splitlines()[0])",
        new="    return body.splitlines()[0]",
        caught_by="test_handoffs.py",
    ),
]
