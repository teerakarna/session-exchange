"""The hook entrypoint. One function, dispatched on the event that fired.

What each event is for:

- **SessionStart** - resolve the root, seed this session's claim, and inject whatever the root has
  to say: problems, then who else is here, then what is waiting for this session, then the
  migration guard. Fires on startup, resume,
  clear and compact, so it has to be safe to run repeatedly against state it may already have
  written.
- **SessionEnd** - clear the claim. This is what makes "set your row to idle when you are done" stop
  depending on a session remembering to, which it reliably did not.

- **Stop** - report a handoff posted since this session was last shown the set, and nothing else.
  It fires after every turn, and what a Stop hook prints makes Claude continue, so anything it
  says that is not new costs a forced turn each time (#123). Claude Code overrides a Stop hook
  after eight such blocks in a row, so a hook that repeats itself is not just noisy, it is
  eventually ignored.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import claims
import exchange_root
import handoffs
import hookio
import legacy
import registry
import store

# How many store problems one session start will carry. A cap rather than the whole list, because a
# store with fifty unreadable files would otherwise put fifty lines into every session on the
# machine and push out the thing the session was started to do. Not a setting in the marker: the
# marker's caps bound *content*, which is a judgement about how much detail is useful, and this
# bounds a fault report, where the only useful number is "enough to act on one". The remainder is
# counted, never dropped, which is the same rule `store.capped_list` states for a claim's lists.
MAX_PROBLEMS = 3


def session_start(data, root, lines):
    session_id = data.get("session_id")
    # The payload has no display name, so it comes from the registry - looked up by the id the
    # payload does carry, rather than by walking the process tree, which is the same answer for the
    # price of one directory read. Every row, read once: presence below needs the same rows, and a
    # second `entries()` would parse every session file again on every start, resume and compact.
    rows = registry.entries(live_only=False, peers_only=False)
    known = registry.by_session_id(session_id, rows=rows) or {}
    # A background job fires SessionStart with its own id, so without this the root gets two claims
    # for what the user thinks is one session, each with the same `name` copied out of the
    # registry, and `SessionEnd` clears only the one that ended. Nothing then renders that leftover
    # as anything but a peer. `registry.is_peer` rather than a comparison here, so the absent-kind
    # default lives in one place - and it is that default which handles the empty row: an id the
    # registry has never heard of reads as a peer and still seeds, because "no row yet" is a timing
    # question and refusing it would be a session with no presence at all. An `if known and ...` in
    # front of this was the first cut and was dead, `is_peer({})` being true already.
    #
    # Returning rather than seeding-and-saying-nothing-else: the legacy warnings below go into the
    # same conversation the interactive half already got them in, so emitting them here is the
    # duplicate rendering this plugin exists to stop, one layer down. See #31.
    #
    # Best effort, and it rests on an ordering nothing here controls: the job's own registry file
    # has to exist by the time its SessionStart fires. If it is written after, `known` is empty, the
    # job reads as a peer and seeds a claim anyway. What contains that is not this guard but
    # `presence` hiding a non-peer's claim while the job runs, then SessionEnd clearing it and the
    # stale mark once its session has gone, so do not lean
    # on this as though it were sufficient. The payload carries nothing that says a person did not
    # start the process, so there is no second signal to branch on yet. See #69.
    if not registry.is_peer(known):
        return
    cwd = data.get("cwd") or os.getcwd()
    claim, problem = claims.seed(root, session_id, cwd, name=known.get("name"))
    if problem:
        lines.append(hookio.problem(problem))

    config, config_problem = store.config(root)
    if config_problem:
        lines.append(hookio.problem(config_problem))

    # #32. `show` names an unreadable record by filename and this said nothing, so the one place
    # every session is guaranteed to look was the one place a corrupt store was invisible. `show`
    # is a command somebody has to think to run, which is the failure this plugin was built about.
    #
    # Both record types, not just claims. Claims were what #32 reported and the handoff half is the
    # same silence one directory over - the live pre-#44 record on this machine is a handoff, and
    # it is reported by `show`, by `doctor`, and until now by nothing a session sees. The added
    # cost is one directory read plus one per handoff for its moves, which is the read `show`
    # already does and which the handoff rendering below needs anyway.
    held, problems = claims.load_all(root)
    stored, found = handoffs.load_all(root)
    problems += found
    for problem in problems[:MAX_PROBLEMS]:
        lines.append(hookio.problem(problem))
    if len(problems) > MAX_PROBLEMS:
        # Counted rather than truncated silently, and it names the command that shows the rest. A
        # report that quietly stops at three reads exactly like a store with three faults in it.
        lines.append(
            hookio.problem(
                f"and {len(problems) - MAX_PROBLEMS} more problem(s) in the store; "
                "`exchange show` lists all of them"
            )
        )

    lines += presence(root, held, session_id, config, rows)
    # The claim on disk when seeding it failed, rather than none: a seed that could not write still
    # leaves whatever the session claimed before, and that is still where it said it is working.
    own = claim or next((c for c in held if c.get("session_id") == session_id), {})
    repos, paths = where(root, own, cwd)
    mine = addressed(stored, session_id, repos, paths)
    lines += waiting(mine, config)
    # What was just shown, so the first Stop has something to compare against. Only when the claim
    # exists: with nowhere to record it, `stop` stays silent rather than guess.
    if claim:
        recorded = claims.mark_seen(root, session_id, {record["id"] for record, _ in mine})
        if recorded:
            lines.append(hookio.problem(recorded))

    # The migration guard stays last, after presence and handoffs, because it is what tells the
    # reader whether the blocks above are the only ones of their kind in the context: a
    # half-migrated machine looks identical to a finished one at the output, and this line is the
    # only thing that distinguishes them.
    state = legacy.report(root)
    if state["double_fire"]:
        # `scoped`, not `wired`. With a machine-wide wiring in place too, naming everything here
        # would put a script into this warning whose wiring is not under this root at all, and send
        # whoever reads it looking through settings files that do not mention it.
        scoped = sorted({name for _, name in state["scoped"]})
        lines.append(
            hookio.problem(
                f"{len(scoped)} legacy hook script(s) still wired: {', '.join(scoped)}. "
                "They fire alongside this plugin, so presence and handoffs are rendered twice. "
                "Run `exchange doctor` for where the wiring is."
            )
        )
    if state["machine_wide"]:
        # Separate line, not a softer version of the one above. A machine-wide wiring is not this
        # root being rendered twice, it is another root being rendered here at all, and a session
        # that has just been handed a list of somebody else's claims needs to be told which of the
        # two it is looking at.
        names = sorted({name for _, name in state["machine_wide"]})
        lines.append(
            hookio.problem(
                f"{len(names)} legacy hook script(s) wired machine-wide: {', '.join(names)}. "
                "They fire for every session on this machine whatever root it belongs to, so "
                "presence shown above them may belong to a different environment."
            )
        )
    for problem in state["problems"]:
        lines.append(hookio.problem(problem))


def presence(root, held, session_id, config, rows):
    """Who else is under this root and what they say they are doing, as context lines.

    Other sessions only: a session reading its own claim back is being told what it already knows,
    at the cost of a row. Live peers in full. A claim whose session is not running - no registry
    row, or a row whose pid is dead or now belongs to another process (#66), which is what a crash
    leaves - is counted rather than rendered,
    because a stale row that reads as current is worse than no row, and counted rather than dropped,
    because a claim nobody cleared is a fault somebody should be able to see. The count says where
    the files are, since nothing removes them on its own: absence from the registry is also what a
    session looks like in the moment before its row is written (#69), so pruning on it would delete
    live claims. A claim held by a live non-peer is neither: it is hidden while the job runs and
    counted as stale once it exits, which is where #69's race leaves one. Nothing at all
    when there is nobody else, for the reason `hookio.emit` gives.

    The root's name heads the block because a machine-wide legacy wiring can put another root's
    presence into the same context, and the reader has to be able to tell which one this is. It is
    marker text, typed by hand, so it goes through `store.printable` like anything else a render
    did not write itself.
    """
    others = [claim for claim in held if claim["session_id"] != session_id]
    # Only the rows somebody holds a claim for, because liveness can cost a `ps` and its answer is
    # read nowhere else.
    claimed = {claim["session_id"] for claim in others}
    asked = [row for row in rows if row.get("sessionId") in claimed]
    live = {row.get("sessionId") for row in asked if registry.alive_row(row)}
    peers = {row.get("sessionId") for row in asked if registry.is_peer(row)} & live
    current = [claim for claim in others if claim["session_id"] in peers]
    stale = [claim for claim in others if claim["session_id"] not in live]
    out = []
    if current:
        out.append(
            f"[{hookio.PREFIX}] {len(current)} other session(s) under "
            f"{store.printable(config['name'])}:"
        )
        for claim in current:
            focus = claims.describe_focus(claim, config["max_focus_chars"])
            out.append(f"- {claims.describe_name(claim)}: {focus}")
            for field, shown in claims.describe_scope(claim, config["max_hot_paths"]):
                out.append(f"  {field}: {shown}")
    if stale:
        out.append(
            f"[{hookio.PREFIX}] {len(stale)} claim(s) left by sessions no longer running. "
            f"`exchange show` lists them; once sure they are gone, delete their files under "
            f"{store.printable(str(store.sessions_dir(root)))}"
        )
    return out


def checkout(enclosing):
    """The repo a working tree belongs to: itself, or for a linked worktree, the main one.

    `git_root` stops at the first `.git`, and in a worktree that is a file saying `gitdir:
    <main>/.git/worktrees/<name>`. Named as found, a session in a worktree is in a repo no handoff
    was ever addressed to, which hides the handoffs for the repo it is actually working on. A
    submodule's `.git` is a file too, pointing into `.git/modules`, and stays its own repo: it is
    one, with its own history, and a handoff for the superproject is not about it.

    Anything unreadable or unexpected is the tree as found. A normal clone lands there too, its
    `.git` being a directory. `ValueError` covers both a file that is not UTF-8 and a path holding a
    NUL, which `resolve` refuses with that rather than an `OSError`.

    A bare repo's worktree points into `<name>.git/worktrees`, not `.git/worktrees`, and has no main
    working tree to name, so it too is the tree as found.
    """
    try:
        text = (enclosing / ".git").read_text(encoding="utf-8")
        gitdir = (enclosing / text.partition("gitdir:")[2].strip()).resolve()
    except (OSError, ValueError):
        return enclosing
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return enclosing


def where(root, claim, cwd):
    """The repos and paths a session is working in: what its claim says, and the repo its cwd is in.

    The cwd half is what makes a scope reach a session that never ran `exchange claim`, which is
    most of them. Its repo is the enclosing git root, relative to the exchange root, and only when
    it is under that root: a repo outside it has no name any handoff here could have used.

    The repo only, never where in it the cwd is. `addressed_to` narrows by path only for a session
    that named one, so that a session which said nothing is not narrowed out of the one handoff it
    was for, and a cwd path would narrow exactly those sessions. A cwd is where a session was
    started, not what it is working on. It would also narrow every other repo the claim holds,
    since a claim's paths are not tied to a repo.

    A worktree whose main repo is outside the root keeps its own name, which is the only one under
    the root anything could have addressed it by.

    A root that is itself the repo is the one exception to "the repo only" (#129). Every session in
    it is in `.`, so nothing could address the sessions in one of its folders: work areas kept as
    plain folders of one repo were reachable only by a claim each session had to remember to make,
    and two handoffs in a real trial went unread that way. So there a session is also in the
    top-level folder its cwd is under, as a repo-equivalent. Added, not substituted: `.` still
    reaches everyone, and a scope is still a name rather than a path, so nobody is narrowed out.
    Only the first level, and only when the enclosing tree is the root itself or a worktree of it:
    anywhere else the enclosing repo already is the answer, and nothing here changes it, which
    includes a repo nested inside one of those folders.
    """
    repos, paths = list(claim.get("repos", ())), list(claim.get("paths", ()))
    found = exchange_root.git_root(cwd)
    for enclosing in (checkout(found), found) if found is not None else ():
        if enclosing == root or root in enclosing.parents:
            repos.append(str(enclosing.relative_to(root)))
            break
    if found is not None and checkout(found) == root:
        # Relative to the tree the cwd is in, so a linked worktree of the root places its sessions
        # by the same folder as the main checkout does. A dot-folder is the tool's state or git's,
        # not a work area, and is no scope.
        inside = pathlib.Path(cwd).expanduser().resolve().relative_to(found).parts
        if inside and not inside[0].startswith("."):
            folder = inside[0]
            repos.append(folder)
            # A claim's paths are relative to the root, which is the repo, while a handoff to the
            # folder names paths relative to the folder. Both spellings are kept, so a session that
            # claimed `area/sub` is not narrowed out of `--repo area --path sub`. Wider, never
            # narrower, for the reason `addressed_to` gives about one row too many.
            paths += [p[len(folder) + 1 :] for p in paths if p.startswith(folder + "/")]
    return repos, paths


def addressed(stored, session_id, repos, paths):
    """Handoffs not yet closed that are for this session, newest first.

    Accepted as well as open, because accepted is somebody having taken it on, and that somebody is
    often this session again after a resume. A session is not shown what it posted itself.

    A session with no id in its payload posted nothing anyone could tell was its own, so nothing is
    left out for that reason. Without the guard, every handoff whose sender had no id either would
    compare `None` with `None` and vanish.
    """
    pending = [pair for pair in stored if pair[1] != handoffs.CLOSED]
    mine = [
        (record, status)
        for record, status in pending
        if (session_id is None or record["from"].get("session_id") != session_id)
        and handoffs.addressed_to(record["to"], session_id, repos, paths)
    ]
    mine.sort(key=lambda pair: (pair[0]["created"], pair[0]["id"]), reverse=True)
    return mine


def waiting(mine, config, heading="{n} handoff(s) for this session, newest first."):
    """Context lines for handoffs `addressed` found, and a count of what the cap leaves out.

    Newest first under `max_handoffs_listed`, for the reason `exchange handoff list` gives: the one
    posted a minute ago is the one nobody has read. What the cap leaves out is counted.

    The rest, the ones addressed to somebody else, are neither listed nor counted. They are
    somebody else's to read, and a count of them would be a line in nearly every session on a busy
    root - the always-there section the reader stops looking at. `exchange handoff list` has all of
    them.
    """
    shown = mine[: config["max_handoffs_listed"]]
    width = config["max_focus_chars"]
    out = []
    if shown:
        out.append(
            f"[{hookio.PREFIX}] {heading.format(n=len(mine))} "
            "`exchange handoff accept <id>` takes one on:"
        )
        for record, status in shown:
            out.append(
                f"- {record['id']} ({status}) from {handoffs.describe_sender(record, width)}, "
                f"to {handoffs.describe(record['to'], width)}: "
                f"{handoffs.preview(record['body'], width)}"
            )
        if len(mine) > len(shown):
            out.append(
                f"  +{len(mine) - len(shown)} older not shown: `exchange handoff list` has them"
            )
    return out


def stop(data, root, lines):
    """Say so when a handoff has arrived since this session was last shown the set.

    The set is what SessionStart showed, recorded on the claim as ids. An id not in it is news, said
    once and then recorded. Everything else is silence, and that includes the cases that look like
    they want a message:

    - `stop_hook_active` means this Stop is the continuation a previous one forced. Saying anything
      again chains the turns, which is how a hook runs into the eight-block override.
    - No usable claim means there is nowhere to record what was shown, so nothing said now could be
      kept from being said again after the next turn.
    - A record that could not be written is the same case: reporting it would repeat.
    - A handoff leaving the set, or changing status, is not news. A close or an accept by somebody
      else is not something this session has to act on, and its own `accept` would otherwise be
      announced back to it on the next turn.

    A session with no `handoffs_seen` yet is one whose claim predates this field, so it records the
    set without reporting it. A handoff posted after that session started and before its first Stop
    is baselined unreported, and surfaces at its next SessionStart; only a session that was running
    across the upgrade can be in that position.

    Recorded before it is said, so a report that is lost on the way (a closed pipe, output Claude
    Code drops) is not repeated. Said at most once is the choice: the other order repeats, which is
    the bug.

    No problem lines either, from here or from `main`: a fault that is reported on every turn is the
    behaviour this handler exists to remove.
    """
    if data.get("stop_hook_active") is True:
        return
    session_id = store.safe_id(data.get("session_id"))
    if session_id is None:
        return
    claim, _ = store.read_json(claims.path(root, session_id), claims.SCHEMA)
    if claim is None:
        return
    config, _ = store.config(root)
    stored, _ = handoffs.load_all(root)
    repos, paths = where(root, claim, data.get("cwd") or os.getcwd())
    mine = addressed(stored, session_id, repos, paths)
    ids = {record["id"] for record, _ in mine}
    seen = claim.get("handoffs_seen")
    known = set(seen or ())
    # Everything ever shown that still exists, not only what matches now: a session that changes its
    # repos or paths can lose a handoff for a turn and get it back, and that must not read as new.
    # Bounded by the handoffs on disk, so a closed-and-removed one does not stay on the claim.
    kept = (known | ids) & {record["id"] for record, _ in stored}
    # No write when nothing changed, which is nearly every turn: a read-modify-write of the claim
    # file after each one, in every session on the root, is a cost and a window for losing an
    # `exchange claim` made in the same moment.
    if (seen is None or kept != known) and claims.mark_seen(root, session_id, kept):
        return
    if seen is None:
        return
    fresh = [pair for pair in mine if pair[0]["id"] not in known]
    lines += waiting(fresh, config, "{n} new handoff(s) for this session, newest first.")


def session_end(data, root, lines):
    problem = claims.clear(root, data.get("session_id"))
    if problem:
        # Worth saying even though nobody may read it: a claim that outlives its session shows up as
        # a live peer to everyone else, which is the wrong-and-not-visibly-wrong state again.
        lines.append(hookio.problem(problem))


HANDLERS = {
    "SessionStart": session_start,
    "Stop": stop,
    "SessionEnd": session_end,
}


def main(default_event, argv=None):
    data = hookio.payload()
    event = hookio.event_name(data, default_event)
    lines = []

    try:
        resolution = exchange_root.resolve(data.get("cwd") or os.getcwd())
        if resolution.problem:
            # Not at Stop, here or below: it would be said again after every turn (#123).
            if event != "Stop":
                lines.append(hookio.problem(resolution.problem))
        elif resolution.root is None:
            # Rule 3. No exchange in this environment, so there is nothing to do and nothing to say.
            return 0
        else:
            handler = HANDLERS.get(event)
            if handler is None:
                lines.append(
                    hookio.problem(
                        f"wired under {event}, which this plugin does not handle. "
                        "Check hooks/hooks.json against how it was installed."
                    )
                )
            else:
                handler(data, resolution.root, lines)
    except Exception as exc:
        if event != "Stop":
            lines.append(
                hookio.problem(
                    f"{type(exc).__name__} in the {event} hook: {exc}. "
                    "Session unaffected; the exchange is not being updated."
                )
            )

    hookio.emit(event, lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "SessionStart"))
