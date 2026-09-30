"""The rules `hook.py` has to keep, one broken way each."""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="hook",
        rule="the handler that runs is the one the payload named, not the one argv carried",
        old="    event = hookio.event_name(data, default_event)",
        new="    event = default_event",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a payload with no cwd falls back to the directory the process is in",
        old='        resolution = exchange_root.resolve(data.get("cwd") or os.getcwd())',
        new='        resolution = exchange_root.resolve(data.get("cwd"))',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a root that resolved to a problem is said out loud, not walked past",
        old=(
            "        if resolution.problem:\n"
            "            lines.append(hookio.problem(resolution.problem))"
        ),
        new="        if resolution.problem:\n            pass",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="no root means no handler ran, rather than one running against a root of None",
        old="        elif resolution.root is None:",
        new="        elif False:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="an event this plugin does not handle is reported, not dispatched to None",
        old="            if handler is None:",
        new="            if False:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="both events are wired, so SessionEnd is not an unhandled event",
        old='HANDLERS = {\n    "SessionStart": session_start,\n    "SessionEnd": session_end,\n}',
        new='HANDLERS = {\n    "SessionStart": session_start,\n}',
        caught_by="test_hook.py",
    ),
    # The wrapper, not any one type it catches. Narrowing it is the mutation because the list is
    # what `hookio.payload` got wrong three times, and here there is no list to get wrong yet.
    Mutation(
        module="hook",
        rule="whatever a handler raises is reported rather than raised out of main",
        old="    except Exception as exc:",
        new="    except ZeroDivisionError as exc:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a hook that had something to complain about still exits 0",
        old="    hookio.emit(event, lines)\n    return 0",
        new="    hookio.emit(event, lines)\n    return 1",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a registry with nothing on this session is no name, not an AttributeError",
        old="    known = registry.by_session_id(session_id, rows=rows) or {}",
        new="    known = registry.by_session_id(session_id, rows=rows)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the claim records where the session actually is",
        old='    cwd = data.get("cwd") or os.getcwd()',
        new="    cwd = None",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the claim carries the display name the registry knows this session by",
        old='claims.seed(root, session_id, cwd, name=known.get("name"))',
        new="claims.seed(root, session_id, cwd, name=None)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a claim that could not be seeded says so",
        old=(
            "    if problem:\n"
            "        lines.append(hookio.problem(problem))\n"
            "\n"
            "    config, config_problem"
        ),
        new=(
            "    if False:\n"
            "        lines.append(hookio.problem(problem))\n"
            "\n"
            "    config, config_problem"
        ),
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="config that could not be read is reported rather than quietly defaulted",
        old="    if config_problem:\n        lines.append(hookio.problem(config_problem))",
        new="    if config_problem:\n        pass",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the migration warning is conditional on legacy hooks being wired",
        old='    if state["double_fire"]:',
        new="    if True:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the warning names the scripts it found wired",
        old='        scoped = sorted({name for _, name in state["scoped"]})',
        new="        scoped = []",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="one script wired in two settings files is one script, not two",
        old='        scoped = sorted({name for _, name in state["scoped"]})',
        new='        scoped = sorted([name for _, name in state["scoped"]])',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        # The doubled-fire warning names the wirings under this root, not every wiring found. Naming
        # all of them puts a machine-wide script into a warning about this root's own settings files
        # and sends whoever reads it through files that never mention it.
        rule="the doubled-fire warning names only the wirings that belong to this root",
        old='        scoped = sorted({name for _, name in state["scoped"]})',
        new='        scoped = sorted({name for _, name in state["wired"]})',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="whatever else the legacy scan found is injected too",
        old='    for problem in state["problems"]:\n        lines.append(hookio.problem(problem))',
        new='    for problem in state["problems"]:\n        pass',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a claim that could not be cleared is reported, not left looking like a live peer",
        old='    problem = claims.clear(root, data.get("session_id"))\n    if problem:',
        new='    problem = claims.clear(root, data.get("session_id"))\n    if False:',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        # #31. Without it the root gets two claims for one session, both carrying the same registry
        # name, and SessionEnd clears only the one that ended.
        rule="a background job seeds no claim of its own",
        old="    if not registry.is_peer(known):\n        return",
        new="    if False:\n        return",
        caught_by="test_hook.py",
    ),
    # #32. The hook was silent about a store `show` names by filename, in the one place every
    # session is guaranteed to look.
    Mutation(
        module="hook",
        rule="a corrupt record reaches the session that starts, not only `show`",
        old=(
            "    for problem in problems[:MAX_PROBLEMS]:\n"
            "        lines.append(hookio.problem(problem))"
        ),
        new="    for problem in []:\n        lines.append(hookio.problem(problem))",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="both record types are enumerated, not just the one the issue reported",
        old="    stored, found = handoffs.load_all(root)\n    problems += found",
        new="    stored, found = handoffs.load_all(root)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the cap on injected problems is a cap",
        old="    for problem in problems[:MAX_PROBLEMS]:",
        new="    for problem in problems:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and what it leaves out is counted rather than dropped",
        old="    if len(problems) > MAX_PROBLEMS:",
        new="    if False:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="presence is rendered at session start, not only by `exchange show`",
        old="    lines += presence(root, held, session_id, config, rows)",
        new="    lines += presence(root, [], session_id, config, rows)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a session is not shown its own claim as another session",
        old='    others = [claim for claim in held if claim["session_id"] != session_id]',
        new="    others = list(held)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a claim whose session is gone is not rendered as current",
        old='    live = {row.get("sessionId") for row in rows if registry.alive(row.get("pid"))}',
        new='    live = {row.get("sessionId") for row in rows}',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and it is counted rather than dropped",
        old="    if stale:",
        new="    if False:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="nobody else here means no presence block at all",
        old="    if current:\n        out.append(",
        new="    if True:\n        out.append(",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the root's name is stripped before it reaches the context",
        old="            f\"{store.printable(config['name'])}:\"",
        new="            f\"{config['name']}:\"",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a live background job's claim is not rendered as a peer",
        old='    peers = {row.get("sessionId") for row in rows if registry.is_peer(row)} & live',
        new='    peers = {row.get("sessionId") for row in rows} & live',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and it is not counted as a session that has stopped either",
        old='    stale = [claim for claim in others if claim["session_id"] not in live]',
        new='    stale = [claim for claim in others if claim["session_id"] not in peers]',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the registry is read with every kind of row, so a background job is recognised",
        old="    rows = registry.entries(live_only=False, peers_only=False)",
        new="    rows = registry.entries(live_only=False)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a peer's focus is stripped before it reaches the context",
        old='            focus = claims.describe_focus(claim, config["max_focus_chars"])',
        new='            focus = claim.get("focus")',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and capped at the marker's width, not the schema default",
        old='            focus = claims.describe_focus(claim, config["max_focus_chars"])',
        new="            focus = claims.describe_focus(claim, 240)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a peer's name is stripped before it reaches the context",
        old='            out.append(f"- {claims.describe_name(claim)}: {focus}")',
        new="            out.append(f\"- {claim.get('name')}: {focus}\")",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a peer's scope is rendered with it, capped at the marker's count",
        old='claims.describe_scope(claim, config["max_hot_paths"])',
        new="claims.describe_scope(claim, 6)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and not only its focus",
        old="            for field, shown in claims.describe_scope(",
        new="            for field, shown in [] and claims.describe_scope(",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the stale count says where the files are, since nothing removes them",
        old='            f"{store.printable(str(store.sessions_dir(root)))}"',
        new='            f""',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and the path is stripped, since a directory name can carry an escape",
        old="store.printable(str(store.sessions_dir(root)))",
        new="store.sessions_dir(root)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a handoff scoped to a claimed repo reaches the session claiming it",
        old='    repos, paths = list(claim.get("repos", ())), list(claim.get("paths", ()))',
        new='    repos, paths = [], list(claim.get("paths", ()))',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and a claimed path narrows",
        old='    repos, paths = list(claim.get("repos", ())), list(claim.get("paths", ()))',
        new='    repos, paths = list(claim.get("repos", ())), []',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the repo a session's cwd is in counts, claimed or not",
        old="        repos.append(str(enclosing.relative_to(root)))",
        new="        pass",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a repo outside the root has no name under it",
        old="        if enclosing == root or root in enclosing.parents:",
        new="        if True:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a root that is itself a repo is one",
        old="        if enclosing == root or root in enclosing.parents:",
        new="        if root in enclosing.parents:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="handoffs are rendered at session start",
        old="    lines += waiting(stored, session_id, repos, paths, config)",
        new="    lines += waiting([], session_id, repos, paths, config)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a closed handoff is neither listed nor counted",
        old="    pending = [pair for pair in stored if pair[1] != handoffs.CLOSED]",
        new="    pending = list(stored)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a session is not shown what it posted",
        old='record["from"].get("session_id") != session_id)',
        new="True)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="newest first, so the cap keeps the newest",
        old='    mine.sort(key=lambda pair: (pair[0]["created"], pair[0]["id"]), reverse=True)',
        new='    mine.sort(key=lambda pair: (pair[0]["created"], pair[0]["id"]))',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the marker caps how many are listed",
        old='    shown = mine[: config["max_handoffs_listed"]]',
        new="    shown = mine",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and what the cap leaves out is counted",
        old="        if len(mine) > len(shown):",
        new="        if False:",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a handoff row is bounded by the marker's width",
        old='    width = config["max_focus_chars"]\n    out = []',
        new="    width = 240\n    out = []",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="nothing for this session means no handoff heading",
        old="    if shown:\n        out.append(",
        new="    if True:\n        out.append(",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a session with no id does not take every sender with no id for itself",
        old="        if (session_id is None or ",
        new="        if (False or ",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the claim on disk still places a session whose seed failed",
        old='    own = claim or next((c for c in held if c.get("session_id") == session_id), {})',
        new="    own = claim or {}",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a cwd in no repo is not handed to checkout",
        old="(checkout(found), found) if found is not None else ()",
        new="(checkout(found), found)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a linked worktree is in the repo it belongs to",
        old="        return gitdir.parent.parent.parent",
        new="        return enclosing",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a relative gitdir is relative to the worktree, not to wherever the hook runs",
        old='        gitdir = (enclosing / text.partition("gitdir:")[2].strip()).resolve()',
        new='        gitdir = pathlib.Path(text.partition("gitdir:")[2].strip()).resolve()',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a submodule is not taken for a worktree",
        old='    if gitdir.parent.name == "worktrees" and ',
        new='    if gitdir.parent.name in ("worktrees", "modules") and ',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="and neither is a bare repo's worktree",
        old=' and gitdir.parent.parent.name == ".git":',
        new=":",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a .git file resolve refuses is the tree as found, not a failed start",
        old="    except (OSError, ValueError):\n        return enclosing",
        new="    except OSError:\n        return enclosing",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a tie on time is broken by id, so the order is the same every run",
        old='    mine.sort(key=lambda pair: (pair[0]["created"], pair[0]["id"]), reverse=True)',
        new='    mine.sort(key=lambda pair: pair[0]["created"], reverse=True)',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a worktree whose main repo is outside the root keeps its own name",
        old="(checkout(found), found) if found",
        new="(checkout(found),) if found",
        caught_by="test_hook.py",
    ),
]
