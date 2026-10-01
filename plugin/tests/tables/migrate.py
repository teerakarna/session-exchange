"""The rules `migrate.py` has to keep, one broken way each.

This is the one module that writes what the ledger said into the store, so its failures land in
another session's context rather than in front of the person who ran it: a handoff posted to a scope
nobody reads, a second copy of one already imported, or half an import with no way to tell it from
the whole.
"""

from .shape import Mutation

# The branch both write loops share, up to the verb that tells them apart.
FAILED = (
    "        if problem:\n            problems.append(problem)\n"
    '        else:\n            lines.append(f"'
)
FAILED_NOT = FAILED.replace("if problem:", "if False:", 1)

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
        old=(
            "    parts = [ledger.normalise_label(part)"
            " for part in label.split(reconcile.RECIPIENT_JOIN)]"
        ),
        new="    parts = [part for part in label.split(reconcile.RECIPIENT_JOIN)]",
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
        old='    if fault:\n        return None, f"the route for',
        new='    if False:\n        return None, f"the route for',
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a route's paths are carried, not just its repo",
        old='handoffs.to_scope(repo=scope.get("repo"), paths=scope.get("paths", ()))',
        new='handoffs.to_scope(repo=scope.get("repo"))',
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
        old="    if problem and not _emptied(text, section):",
        new="    if False:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="an unreadable record in the store blocks the import",
        old="    problems = [*problems, *plan.problems, *route_problems]",
        new="    problems = [*plan.problems, *route_problems]",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="two entries reconcile cannot tell apart block the import",
        old="    problems = [*problems, *plan.problems, *route_problems]",
        new="    problems = [*problems, *route_problems]",
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
    Mutation(
        module="migrate",
        rule="a recipient group in the marker is sorted, so it matches however it is written",
        old="    return reconcile.RECIPIENT_JOIN.join(sorted(part for part in parts if part))",
        new="    return reconcile.RECIPIENT_JOIN.join(part for part in parts if part)",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="two route keys that normalise alike are a problem, not a last-wins",
        old="        elif key in table:",
        new="        elif False:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="an empty route label is a problem",
        old="        if not key:",
        new="        if False:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="route problems block the import",
        old="    problems = [*problems, *plan.problems, *route_problems]",
        new="    problems = [*problems, *plan.problems]",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="an entry with no recipient is a problem, not a crash",
        old="    if not entry.recipients:",
        new="    if False:",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a blank section is an empty ledger, not a problem",
        old="    return bool(bodies) and not any(body.strip() for body in bodies)",
        new="    return False",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a section with text and no entry is still a problem",
        old="    return bool(bodies) and not any(body.strip() for body in bodies)",
        new="    return bool(bodies)",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="every matching heading has to be blank, not just one",
        old="    return bool(bodies) and not any(body.strip() for body in bodies)",
        new="    return bool(bodies) and not all(body.strip() for body in bodies)",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="an open orphan is stranded, a closed one is not",
        old='if status.get(record["id"]) != handoffs.CLOSED]',
        new="if True]",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a stranded row is outstanding",
        old="len(prepared.closes) + len(prepared.stranded)",
        new="len(prepared.closes)",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="the id comes from the key, so a concurrent second run is refused at the filesystem",
        old="            handoff_id=id_of(entry),",
        new="            handoff_id=None,",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="the id covers the whole key, not just the date",
        old="    key = json.dumps(reconcile.imported_of(entry), sort_keys=True)",
        new="    key = str(entry.date)",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a failed post is reported",
        old=f"{FAILED}posted",
        new=f"{FAILED_NOT}posted",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a failed close is reported",
        old=f"{FAILED}closed",
        new=f"{FAILED_NOT}closed",
        caught_by="test_migrate.py",
    ),
    Mutation(
        module="migrate",
        rule="a partial write says how much was made and to run again",
        old="    if problems:\n        done = len(lines)",
        new="    if False:\n        done = len(lines)",
        caught_by="test_migrate.py",
    ),
]
