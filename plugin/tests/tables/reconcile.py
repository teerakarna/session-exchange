"""The rules `reconcile.py` has to keep, one broken way each.

The module decides whether an import is safe to run twice, and its failure is an import that
quietly duplicates, merges or skips. Nobody watches for that by construction, since the point of
the importer is that it runs once, so each rule here gets a mutation rather than trust.
"""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="reconcile",
        rule="recipient order carries nothing, so A + B and B + A are one route",
        old=(
            "    right = RECIPIENT_JOIN.join("
            "sorted(ledger.normalise_label(part) for part in recipients))"
        ),
        new="    right = RECIPIENT_JOIN.join(ledger.normalise_label(part) for part in recipients)",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="the sender is normalised like the recipients",
        old='    left = ledger.normalise_label(sender) if sender else ""',
        new='    left = sender or ""',
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="the headline is stripped after truncating, so the key is idempotent",
        old="    return folded[:HEADLINE_PREFIX].strip()",
        new="    return folded[:HEADLINE_PREFIX]",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="the headline key folds case",
        old='    folded = re.sub(r"\\s+", " ", headline).strip().casefold()',
        new='    folded = re.sub(r"\\s+", " ", headline).strip()',
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="the prefix is long enough not to merge two handoffs on one route",
        old="HEADLINE_PREFIX = 64",
        new="HEADLINE_PREFIX = 20",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="the prefix is short enough to absorb an edit to the tail",
        old="HEADLINE_PREFIX = 64",
        new="HEADLINE_PREFIX = 400",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="the key reads the original headline, which survives acknowledgement",
        old="    return Key(route, headline_key(entry.original_headline), entry.date)",
        new="    return Key(route, headline_key(entry.headline), entry.date)",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="an entry with no route has no key, rather than an empty one",
        old='    if route.strip(ROUTE_JOIN + " ") == "":',
        new="    if False:",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="a stored key is re-normalised, because the file is hand-editable",
        old=(
            "    return Key(route_key(left or None, recipients), headline_key(headline), "
            'imported.get("date"))'
        ),
        new='    return Key(route, headline, imported.get("date"))',
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="a stored block missing a half reads as not imported",
        old="    if not route or not headline:\n        return None",
        new="    if not route and not headline:\n        return None",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="an absent date is omitted, not stored as null",
        old='    if key.date:\n        block["date"] = key.date',
        new='    block["date"] = key.date',
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="a closed entry maps to closed",
        old="    return STATUS_CLOSED if entry.closed else STATUS_OPEN",
        new="    return STATUS_OPEN",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="the body is verbatim inside, trimmed only at the ends",
        old="    return entry.block.strip()",
        new='    return " ".join(entry.block.split())',
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="a stored key that drifted from the source is a change",
        old="    if stored != fresh:",
        new="    if False:",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="two items sharing a key are a problem, never a silent merge",
        old="        if len(group) > 1:",
        new="        if len(group) > 2:",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="an entry with no route is reported, not dropped",
        old="    for entry in unkeyed:",
        new="    for entry in []:",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="stored rows sharing a key are a problem too",
        old="    problems.extend(stored_problems)",
        new="    pass",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="a closed entry never imported is skipped, not created",
        old="            if entry.closed:",
        new="            if False:",
        caught_by="test_reconcile.py",
    ),
    Mutation(
        module="reconcile",
        rule="a stored row with no source entry is an orphan",
        old="if key not in source]",
        new="if False]",
        caught_by="test_reconcile.py",
    ),
]
