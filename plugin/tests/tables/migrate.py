"""The rules `migrate.py` has to keep, one broken way each.

This is the one module that writes what the ledger said into the store, so its failures land in
another session's context rather than in front of the person who ran it: a handoff posted to a scope
nobody reads, a second copy of one already imported, or half an import with no way to tell it from
the whole.
"""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="migrate",
        rule="a relative ledger path is read against the root, not the working directory",
        old="    return path if path.is_absolute() else pathlib.Path(root) / path",
        new="    return path",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="route keys are normalised like the labels they are matched against",
        old="        ledger.normalise_label(label): scope for label, scope in",
        new="        label: scope for label, scope in",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a recipient group can be mapped as a whole",
        old="    if group in table:",
        new="    if False:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="recipients on more than one scope are refused, since a handoff has one",
        old="    if len({json.dumps(scope, sort_keys=True) for scope in scopes}) > 1:",
        new="    if len({json.dumps(scope, sort_keys=True) for scope in scopes}) > 2:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a route goes through the store's own scope check",
        old='    return handoffs.to_scope(repo=scope.get("repo"), paths=scope.get("paths", ()))',
        new="    return scope, None",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a route's paths are carried, not just its repo",
        old='    return handoffs.to_scope(repo=scope.get("repo"), paths=scope.get("paths", ()))',
        new='    return handoffs.to_scope(repo=scope.get("repo"))',
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="only a move to closed is written back",
        old="    return bool(status) and status[1] == reconcile.STATUS_CLOSED",
        new="    return bool(status) and status[1] == reconcile.STATUS_OPEN",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a closure that is written is not also reported as drift",
        old='        if not (field == "status" and _is_close(change))',
        new="        if True",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="the section named in the marker is the one read",
        old="    entries, problem = ledger.entries(text, section)",
        new="    entries, problem = ledger.entries(text)",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a ledger with no readable section is a problem, not an empty import",
        old="    if problem:\n        return Prepared(path, 0, empty, [], [], [], [problem])",
        new="    if False:\n        return Prepared(path, 0, empty, [], [], [], [problem])",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="an unreadable record in the store blocks the import",
        old="    problems = [*problems, *plan.problems]",
        new="    problems = [*plan.problems]",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="two entries reconcile cannot tell apart block the import",
        old="    problems = [*problems, *plan.problems]",
        new="    problems = [*problems]",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="an unroutable entry blocks the import",
        old="        if fault:\n            problems.append(fault)",
        new="        if fault:\n            pass",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="any problem means nothing is written",
        old="    if prepared.problems:",
        new="    if False:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="created is the ledger's date",
        old="            at=created_of(entry),",
        new="            at=None,",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="an undated entry has no date of its own, rather than an invented one",
        old='    return f"{entry.date}T00:00:00Z" if entry.date else None',
        new='    return f"{entry.date}T00:00:00Z" if entry.date else store.now()',
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="the record carries the importer's key, or a second run posts it again",
        old="            imported=reconcile.imported_of(entry),",
        new="            imported=None,",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="the sender is the ledger's sender",
        old="            name=entry.sender,",
        new="            name=None,",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="planned closes are written",
        old="    for change in prepared.closes:",
        new="    for change in []:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a close names this command as the mover",
        old="root, handoff_id, handoffs.CLOSED, by=BY,",
        new="root, handoff_id, handoffs.CLOSED, by=None,",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a planned close is outstanding work",
        old="    return len(prepared.plan.create) + len(prepared.closes)",
        new="    return len(prepared.plan.create)",
        caught_by="test_migrate.py",
    ),
]
