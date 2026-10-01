"""The mutation tables, one file per module, and the accounting that says every module has a home.

Split out of `mutate.py` because keeping them there made the narrowed sweep narrow nothing (#36).
`mutate.py` is in `INSTRUMENT`, so a change to it resweeps every table - correctly, since a change
to the harness can weaken every verdict at once. But the tables lived there too, and this repo's
rule is that a fix adds a mutation, so nearly every PR edited `mutate.py`, tripped `INSTRUMENT` and
paid the full sweep. The narrowing only ever applied to the PR this repo tries not to produce: one
that changes behaviour and asserts nothing new about it.

**One file per module rather than one file holding them all**, which is the part that makes the
narrowing work rather than just moving code. `targets` maps a changed path to the modules worth
sweeping, and it is pure: all it has is the path. `tables/handoffs.py` names its module in the path,
so a diff that adds a mutation there sweeps `handoffs` and nothing else. A single `tables.py` would
have to be swept wide, because nothing in a path can say which table inside the file changed, and
the sweep would be exactly as unnarrowed as before with the code in a different place.

`shape.py` and this file are instrument, not tables: the first decides what a table entry is and the
second decides which tables exist, so a change to either can invalidate any verdict. Both are in
`INSTRUMENT` alongside `mutate.py` and `run.py`.
"""

from . import (
    claims,
    exchange_root,
    handoffs,
    hook,
    hookio,
    ledger,
    legacy,
    migrate,
    reconcile,
    registry,
    store,
    validate,
)
from .shape import Mutation  # noqa: F401  - re-exported; the tables and `mutate.py` both import it

TABLES = {
    "claims": claims.MUTATIONS,
    "exchange_root": exchange_root.MUTATIONS,
    "handoffs": handoffs.MUTATIONS,
    "hook": hook.MUTATIONS,
    "hookio": hookio.MUTATIONS,
    "ledger": ledger.MUTATIONS,
    "legacy": legacy.MUTATIONS,
    "migrate": migrate.MUTATIONS,
    "reconcile": reconcile.MUTATIONS,
    "registry": registry.MUTATIONS,
    "store": store.MUTATIONS,
    "validate": validate.MUTATIONS,
}

# Modules with no table yet, listed rather than merely absent so that the debt is a thing you have
# to look at and a new module cannot join it by accident. `test_mutations.py` asserts these two sets
# plus the keys of TABLES are exactly what is in `plugin/lib`, so adding a module without deciding
# which of the three it belongs in fails the build. The mechanism came from issue #8.
#
# Empty, and kept rather than deleted so the next module has somewhere honest to go. `ledger` and
# `reconcile` sat here until #55 gave them tables, ahead of `migrate`, which is their first caller.
# They had been in `DECLINED` before that, on a reason that described other modules (#40).
NOT_YET = set()

# Not "not yet". Decided against, with the reason next to the name, because a debt list that
# silently contains permanent entries stops being a debt list. Reversing one of these is an edit to
# this dict, which is the point of writing the reason down rather than the decision.
#
# One entry, and the reason is specific to it rather than a general argument about cheap feedback
# loops. `cli` is 400-odd lines of argument parsing and output formatting, every path of it reached
# by a person who typed the command and is looking at the answer, and `test_cli.py` drives all of it
# end to end. That is the trade the sweep loses on. It is a claim about `cli` and cannot be
# recycled: the two it was recycled for have no caller, so there is no person and no answer to read.
DECLINED = {
    "cli": "argument parsing and output formatting, wrong in front of the person who typed it",
}

# The union is what the accounting in `test_mutations.py` and the `--since` notes in `mutate.py`
# read, so the split above costs those callers nothing.
UNSWEPT = NOT_YET | set(DECLINED)
