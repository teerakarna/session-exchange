"""The hook entrypoint. One function, dispatched on the event that fired.

What each event is for:

- **SessionStart** - resolve the root, seed this session's claim, and inject whatever the root has
  to say: problems, then who else is here, then what is waiting for this session, then the
  migration guard. Fires on startup, resume,
  clear and compact, so it has to be safe to run repeatedly against state it may already have
  written.
- **SessionEnd** - clear the claim. This is what makes "set your row to idle when you are done" stop
  depending on a session remembering to, which it reliably did not.

`Stop` is deliberately not wired yet. Its job in the design is catching handoffs posted mid-session,
and the matcher it would call is now here; it goes in as its own change, since a hook on every turn
is a cost every session pays and deserves its own review.
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
    lines += waiting(stored, session_id, repos, paths, config)

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
    row, or a row whose pid is dead, which is what a crash leaves - is counted rather than rendered,
    because a stale row that reads as current is worse than no row, and counted rather than dropped,
    because a claim nobody cleared is a fault somebody should be able to see. The count says where
    the files are, since nothing removes them on its own: absence from the registry is also what a
    session looks like in the moment before its row is written (#69), so pruning on it would delete
    live claims. A claim held by a live non-peer is neither, and is #68's to settle. Nothing at all
    when there is nobody else, for the reason `hookio.emit` gives.

    The root's name heads the block because a machine-wide legacy wiring can put another root's
    presence into the same context, and the reader has to be able to tell which one this is. It is
    marker text, typed by hand, so it goes through `store.printable` like anything else a render
    did not write itself.
    """
    live = {row.get("sessionId") for row in rows if registry.alive(row.get("pid"))}
    peers = {row.get("sessionId") for row in rows if registry.is_peer(row)} & live
    others = [claim for claim in held if claim["session_id"] != session_id]
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
    """
    repos, paths = list(claim.get("repos", ())), list(claim.get("paths", ()))
    enclosing = exchange_root.git_root(cwd)
    if enclosing is not None:
        enclosing = checkout(enclosing)
    if enclosing is not None and (enclosing == root or root in enclosing.parents):
        repos.append(str(enclosing.relative_to(root)))
    return repos, paths


def waiting(stored, session_id, repos, paths, config):
    """Handoffs not yet closed that are for this session, as context lines, and a count of the rest.

    Newest first under `max_handoffs_listed`, for the reason `exchange handoff list` gives: the one
    posted a minute ago is the one nobody has read. What the cap leaves out is counted.

    Accepted as well as open, because accepted is somebody having taken it on, and that somebody is
    often this session again after a resume. A session is not shown what it posted itself.

    A session with no id in its payload posted nothing anyone could tell was its own, so nothing is
    left out for that reason. Without the guard, every handoff whose sender had no id either would
    compare `None` with `None` and vanish.

    The rest are neither listed nor counted. They are somebody else's to read, and a count of them
    would be a line in nearly every session on a busy root - the always-there section the reader
    stops looking at. `exchange handoff list` has all of them.
    """
    pending = [pair for pair in stored if pair[1] != handoffs.CLOSED]
    mine = [
        (record, status)
        for record, status in pending
        if (session_id is None or record["from"].get("session_id") != session_id)
        and handoffs.addressed_to(record["to"], session_id, repos, paths)
    ]
    mine.sort(key=lambda pair: (pair[0]["created"], pair[0]["id"]), reverse=True)
    shown = mine[: config["max_handoffs_listed"]]
    width = config["max_focus_chars"]
    out = []
    if shown:
        out.append(
            f"[{hookio.PREFIX}] {len(mine)} handoff(s) for this session, newest first. "
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


def session_end(data, root, lines):
    problem = claims.clear(root, data.get("session_id"))
    if problem:
        # Worth saying even though nobody may read it: a claim that outlives its session shows up as
        # a live peer to everyone else, which is the wrong-and-not-visibly-wrong state again.
        lines.append(hookio.problem(problem))


HANDLERS = {
    "SessionStart": session_start,
    "SessionEnd": session_end,
}


def main(default_event, argv=None):
    data = hookio.payload()
    event = hookio.event_name(data, default_event)
    lines = []

    try:
        resolution = exchange_root.resolve(data.get("cwd") or os.getcwd())
        if resolution.problem:
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
