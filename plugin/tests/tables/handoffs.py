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
            "    phrase = f\"{repo}: {', '.join(store.printable(p) for p in paths)}\" "
            "if paths else repo"
        ),
        new="    phrase = repo",
        caught_by="test_handoffs.py",
    ),
    # #61. The width bound on each of the three, separately, for the reason the stripping entries
    # below are separate: a cap on two of them reads as done and the third is the 23 KB row.
    Mutation(
        module="handoffs",
        rule="and the phrase is bounded in width, a path list having no length limit",
        old="    return store.capped_text(phrase, cap)",
        new="    return phrase",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="so is a session scope, which is the branch that returns before the other one",
        old=(
            "        return store.capped_text("
            "f\"session {store.printable(to['session_id'])}\", cap)"
        ),
        new="        return f\"session {store.printable(to['session_id'])}\"",
        caught_by="test_handoffs.py",
    ),
    # #46. The guard itself moved to `store`, because a claim has the same two fields and the point
    # of the shape is that the two get compared - so its three mutations are in `tables/store.py`
    # now. What stays here is the calling: `to_scope` has to run it, and has to run it over every
    # path rather than the first one, which is the half a guard written for `repo` alone leaves
    # behind.
    Mutation(
        module="handoffs",
        rule="a scope a handoff is addressed to goes through the guard at all",
        old='        fault = store.scope_fault("--repo", repo)',
        new="        fault = None",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so does every path that narrows it",
        old='                fault = store.scope_fault("--path", path)',
        new="                fault = None",
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
        old=(
            "    return store.capped_text(\n"
            '        store.printable(record["from"].get("name") or record["from"]["cwd"]), cap\n'
            "    )"
        ),
        new=(
            "    return store.capped_text(\n"
            '        record["from"].get("name") or record["from"]["cwd"], cap\n'
            "    )"
        ),
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and the body preview, which is the field the issue was filed about",
        old="    return store.capped_text(store.printable(body.splitlines()[0]), cap)",
        new="    return store.capped_text(body.splitlines()[0], cap)",
        caught_by="test_handoffs.py",
    ),
    # #51. `load_all` already refuses a pre-#44 record and names the file and the key, which is all
    # a reader needs to delete a handoff and nothing they need to keep one. The conversion exists;
    # until this, nothing said so.
    Mutation(
        module="handoffs",
        rule="a record written before #44 is reported as convertible, not only as invalid",
        old="        present = [key for key in PRE_44_KEYS if key in record]",
        new="        present = []",
        caught_by="test_cli.py",
    ),
    # Both fields #44 removed, rather than whichever one a record happens to carry. A record with
    # `history` and no `status` is the same record and the same conversion.
    Mutation(
        module="handoffs",
        rule="and dated by either of the two fields it removed",
        old='PRE_44_KEYS = ("status", "history")',
        new='PRE_44_KEYS = ("status",)',
        caught_by="test_cli.py",
    ),
    # #53. Both directions, because a diagnostic that reports every moves directory as an orphan and
    # one that reports none of them are both silent about the real one - the first by drowning it.
    Mutation(
        module="handoffs",
        rule="a moves directory with no record beside it is reported",
        old="        if record.exists():\n            continue",
        new="        if True:\n            continue",
        caught_by="test_cli.py",
    ),
    Mutation(
        module="handoffs",
        rule="and one with its record still there is not",
        old="        if record.exists():",
        new="        if False:",
        caught_by="test_cli.py",
    ),
    # #52. Both directions again. A `resolve` that refuses everything leaves the handoff frozen,
    # which is the state the verb was added for; one that refuses nothing is `set_status` with the
    # already-in-that-status guard taken out, and it is the only verb here that writes a status
    # nothing derived from the moves on disk.
    Mutation(
        module="handoffs",
        rule="a handoff frozen by a tie at its last position can be declared",
        old="    if _settled(seen):",
        new="    if True:",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and one that is not frozen cannot be, resolve not being a second close",
        old="    if _settled(seen):",
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    # The declaration goes after the tie rather than into it. At the tied position it is a third
    # disagreeing move, which is the state it was called to get out of.
    Mutation(
        module="handoffs",
        rule="a declaration lands one past the tie, like every other move",
        old=(
            "    return _move("
            'root, handoff_id, status, 1 + max(e["after"] for e in seen), by, note, at)'
        ),
        new=(
            "    return _move("
            'root, handoff_id, status, max(e["after"] for e in seen), by, note, at)'
        ),
        caught_by="test_handoffs.py",
    ),
    # An unreadable move could be one of the two that are tied, so which statuses disagree cannot
    # be read - and resolving a tie that may not be the tie on disk is the one guess this verb
    # exists to avoid making.
    Mutation(
        module="handoffs",
        rule="a tie with an unreadable move beside it is refused rather than declared",
        old="    if problems:",
        new="    if False:",
        caught_by="test_handoffs.py",
    ),
    # And the report that names the verb names only the handoffs it applies to. Every handoff
    # carrying the recipe is the same as none of them doing: the one that is actually stuck is not
    # findable.
    Mutation(
        module="handoffs",
        rule="the recipe is printed for a frozen handoff and not for a healthy one",
        old="        if faults or _settled(seen):\n            continue",
        new="        if False:\n            continue",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="the sender is bounded in width too, name and cwd both being unbounded in the schema",
        old=(
            "    return store.capped_text(\n"
            '        store.printable(record["from"].get("name") or record["from"]["cwd"]), cap\n'
            "    )"
        ),
        new='    return store.printable(record["from"].get("name") or record["from"]["cwd"])',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so is the body preview, one line being no bound at all on a line with no length",
        old="    return store.capped_text(store.printable(body.splitlines()[0]), cap)",
        new="    return store.printable(body.splitlines()[0])",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a '.' component is spelt away",
        old='    return "/".join(part for part in scope.split("/") if part not in ("", "."))',
        new='    return "/".join(part for part in scope.split("/") if part not in ("",))',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so is an empty one, from a doubled or trailing slash",
        old='    return "/".join(part for part in scope.split("/") if part not in ("", "."))',
        new='    return "/".join(part for part in scope.split("/") if part != ".")',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="the handoff's repo is compared by spelling",
        old='    if spelling(to["repo"]) not in {spelling(repo) for repo in repos}:',
        new='    if to["repo"] not in {spelling(repo) for repo in repos}:',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so is the session's",
        old='    if spelling(to["repo"]) not in {spelling(repo) for repo in repos}:',
        new='    if spelling(to["repo"]) not in set(repos):',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a handoff for another repo is not for this session",
        old='        return False\n    if not to.get("paths")',
        new='        pass\n    if not to.get("paths")',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a session-addressed handoff is for that session only",
        old='        return to["session_id"] == session_id',
        new="        return True",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a session that named no paths is not narrowed out of its repo",
        old='    if not to.get("paths") or not paths:',
        new='    if not to.get("paths"):',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="paths overlap by whole components, not characters",
        old="    return one[:shorter] == other[:shorter]",
        new=(
            '    return "/".join(one).startswith("/".join(other))'
            ' or "/".join(other).startswith("/".join(one))'
        ),
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and in either direction",
        old="    shorter = min(len(one), len(other))",
        new="    shorter = len(one)",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="paths are compared by spelling",
        old="        _overlaps(spelling(wanted), spelling(held))",
        new="        _overlaps(wanted, held)",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="one overlapping path of several is enough",
        old="    return any(\n        _overlaps(",
        new="    return all(\n        _overlaps(",
        caught_by="test_handoffs.py",
    ),
    # `"".split("/")` is `[""]`, one empty component, which overlaps nothing but another empty one.
    Mutation(
        module="handoffs",
        rule="a held path of '.' is the whole repo, not a component named ''",
        old='other.split("/") if other else []',
        new='other.split("/")',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so is a wanted one",
        old='one.split("/") if one else []',
        new='one.split("/")',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a record not named after its id is named stripped (#60)",
        old='f"{store.printable(file.name)} holds the id',
        new='f"{file.name} holds the id',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="a pre-#44 record is named stripped",
        old='f"{store.printable(file.name)} was written before #44',
        new='f"{file.name} was written before #44',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so is the directory it is told to write into",
        old="        moves = store.printable(store.transitions_dir(root, file.stem).name)",
        new="        moves = store.transitions_dir(root, file.stem).name",
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="an orphaned moves directory is named stripped",
        old='f"{store.printable(moves.name)} holds {len(kept)}',
        new='f"{moves.name} holds {len(kept)}',
        caught_by="test_handoffs.py",
    ),
    Mutation(
        module="handoffs",
        rule="and so is the record it is missing",
        old='f"{store.printable(record.name)} beside it',
        new='f"{record.name} beside it',
        caught_by="test_handoffs.py",
    ),
]
