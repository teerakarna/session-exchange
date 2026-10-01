"""The rules `decommission.py` has to keep, one broken way each.

This is the one module that edits a file it does not own and moves files out of `~/.claude/hooks`,
so its failures are a command lost from someone's settings, every session on a machine starting
with a failing hook, or another root's exchange ended from a session that cannot see it.
"""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="decommission",
        rule="a hook entry with no legacy name in it is kept",
        old="                if not names:\n                    kept.append(hook)",
        new="                if False:\n                    kept.append(hook)",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a legacy script run among other commands is left for a person",
        old="                elif any(COMPOUND.search(text) for text in texts):",
        new="                elif False:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a compound command is reported, not just kept",
        old='                    problems.append(\n                        f"a {event} hook runs',
        new='                    (\n                        f"a {event} hook runs',
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="what is removed is named",
        old="                    removed |= names",
        new="                    pass",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a matcher group left with no hooks is taken out",
        old="            if kept or not inner:",
        new="            if True:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="an event left with nothing is taken out, one empty before is left",
        old="        if kept_groups or not groups:",
        new="        if kept_groups:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="an event left with nothing is taken out",
        old="        if kept_groups or not groups:",
        new="        if True:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a hooks block left empty goes too",
        old='    if not events and settings.get("hooks"):',
        new="    if False:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="only settings files under this root are edited",
        old='    for path in sorted({path for path, _ in state["scoped"]}):',
        new='    for path in sorted({path for path, _ in state["wired"]}):',
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a legacy name left outside a hook entry is a problem",
        old="        if left and not faults:",
        new="        if False:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="detection problems block the run",
        old='    problems = list(state["problems"])',
        new="    problems = []",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a script still wired machine-wide is kept, not retired",
        old='    retire = [path for path in state["on_disk"] if path.name not in held]',
        new='    retire = list(state["on_disk"])',
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="any problem means nothing is written",
        old="    if prepared.problems:",
        new="    if False:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="the old copy is kept before the file is rewritten",
        old="            shutil.copy2(path, backup)",
        new="            pass",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="the edit is written",
        old="        problem = store.write_json(path, new)",
        new="        problem = None",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a failed edit stops the scripts from moving",
        old="    if not problems and prepared.retire:",
        new="    if prepared.retire:",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a script is moved aside, not deleted",
        old="                script.rename(retired / script.name)",
        new="                script.unlink()",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a partial run says how much was made and to run again",
        old="    if problems:\n        total",
        new="    if False:\n        total",
        caught_by="test_decommission.py",
    ),
    Mutation(
        module="decommission",
        rule="a stamp is safe in a directory name",
        old='    return store.now().replace("-", "").replace(":", "")',
        new="    return store.now()",
        caught_by="test_decommission.py",
    ),
]
