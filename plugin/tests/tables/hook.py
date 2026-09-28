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
        old="    known = registry.by_session_id(session_id) or {}",
        new="    known = registry.by_session_id(session_id)",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the claim records where the session actually is",
        old='        root, session_id, data.get("cwd") or os.getcwd(), name=known.get("name")',
        new='        root, session_id, None, name=known.get("name")',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="the claim carries the display name the registry knows this session by",
        old='        root, session_id, data.get("cwd") or os.getcwd(), name=known.get("name")',
        new='        root, session_id, data.get("cwd") or os.getcwd(), name=None',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hook",
        rule="a claim that could not be seeded says so",
        old=(
            "    if problem:\n"
            "        lines.append(hookio.problem(problem))\n"
            "\n"
            "    _, config_problem"
        ),
        new=(
            "    if False:\n        lines.append(hookio.problem(problem))\n\n    _, config_problem"
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
]
