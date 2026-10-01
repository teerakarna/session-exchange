"""Migration step 4: lifting a markdown ledger's open handoffs into the store.

`ledger.py` reads the file and `reconcile.py` decides what an import would do. This module is the
part that writes, and the only one: it turns a plan into posts and moves, through `handoffs`, and
nothing else here touches a file except to read the ledger.

**A plan first, and nothing written while it has a problem.** `prepare` does every read and every
decision and returns the whole answer, so a dry run and a real run print the same thing and differ
only in whether `apply` is called. A problem anywhere - an entry `reconcile` cannot tell apart from
another, a recipient with no route, an unreadable record in the store - stops the run before the
first write. A partial import is the hardest state to read back: some rows exist and some do not,
and nothing on disk says which half was meant.

**Addressing comes from the marker.** The ledger names lanes and the store addresses scopes, and
there is no way to derive one from the other, so `legacy_ledger.routes` maps a label to a scope.
Keys are compared normalised, the same way `reconcile` compares labels. An entry addressed to
several labels has to land on one scope, because a handoff has one `to`: either every label maps to
the same scope, or the whole recipient side is mapped as one key. Posting one copy per scope was the
alternative and is wrong here, since the copies would share the importer's key and the next run
would report the pair as a collision it cannot resolve.

**Only a closure is written back.** The ledger stays in use during the dual run, so an entry already
imported can change there. A closure is the one change worth carrying: it becomes a normal move,
the same file `handoff close` writes, with `by` naming this command. Everything else is reported and
left alone. The stored record is written once and never touched again, which is the rule `handoffs`
is built on, so a body edited in the ledger stays as it was imported. And a status moving any other
way - a stored close the ledger still calls open, an acceptance the ledger has no word for - is the
store being ahead of the ledger, which is the direction the migration is going.

**`created` is the ledger's date, not the import's.** Staleness is read off `created`, and an entry
nine days old imported today would otherwise read as fresh, which is the ten-day silent failure this
project started from arriving by a new route. An undated entry gets the time of the import, and that
is the one place it has to be said, so it is said in the report.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import handoffs
import ledger
import reconcile
import store

BY = "exchange migrate --step 4"


class Prepared(NamedTuple):
    """What a run would do, with nothing done.

    `routes` holds the `to` block for each entry in `plan.create`, in the same order. `closes` are
    the updates that carry a closure, which is written. `drift` is every update with a field that is
    not written, paired with just those fields, so an entry closed and edited in the ledger is in
    both.
    """

    path: pathlib.Path
    parsed: int
    plan: reconcile.Plan
    routes: list[dict[str, Any]]
    closes: list[reconcile.Change]
    drift: list[tuple[reconcile.Change, dict[str, tuple[Any, Any]]]]
    problems: list[str]


def ledger_path(root, block):
    """The ledger file named by `legacy_ledger.path`, relative to the root unless absolute."""
    path = pathlib.Path(block["path"]).expanduser()
    return path if path.is_absolute() else pathlib.Path(root) / path


def _route_table(block):
    return {
        ledger.normalise_label(label): scope for label, scope in block.get("routes", {}).items()
    }


def route_of(entry, table):
    """The `to` block for one entry, or `(None, problem)`."""
    group = reconcile.route_key(None, entry.recipients).lstrip(reconcile.ROUTE_JOIN)
    if group in table:
        scopes = [table[group]]
    else:
        missing = [
            label for label in entry.recipients if ledger.normalise_label(label) not in table
        ]
        if missing:
            return None, (
                f"no route for {', '.join(store.printable(label) for label in missing)}: map it in "
                f"legacy_ledger.routes ({store.printable(entry.headline[:60])!r})"
            )
        scopes = [table[ledger.normalise_label(label)] for label in entry.recipients]
    if len({json.dumps(scope, sort_keys=True) for scope in scopes}) > 1:
        return None, (
            f"{len(entry.recipients)} recipients map to different scopes and a handoff has one;"
            f" map {group!r} as a whole in legacy_ledger.routes"
            f" ({store.printable(entry.headline[:60])!r})"
        )
    scope = scopes[0]
    return handoffs.to_scope(repo=scope.get("repo"), paths=scope.get("paths", ()))


def _is_close(change):
    """Whether this update carries a closure, the one kind of change written back."""
    status = change.fields.get("status")
    return bool(status) and status[1] == reconcile.STATUS_CLOSED


def _unwritten(change):
    """The fields of an update that are reported and not written."""
    return {
        field: values
        for field, values in change.fields.items()
        if not (field == "status" and _is_close(change))
    }


def prepare(root, block):
    """Read the ledger and the store and decide everything. Writes nothing."""
    path = ledger_path(root, block)
    empty = reconcile.Plan([], [], [], [], [], [])
    try:
        text = path.read_text("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Prepared(path, 0, empty, [], [], [], [f"cannot read {path}: {type(exc).__name__}"])
    section = block.get("section", ledger.DEFAULT_SECTION)
    entries, problem = ledger.entries(text, section)
    if problem:
        return Prepared(path, 0, empty, [], [], [], [problem])
    held, problems = handoffs.load_all(root)
    plan = reconcile.reconcile(entries, held)
    problems = [*problems, *plan.problems]
    table = _route_table(block)
    routes = []
    for entry in plan.create:
        scope, fault = route_of(entry, table)
        if fault:
            problems.append(fault)
        routes.append(scope)
    closes = [change for change in plan.update if _is_close(change)]
    drift = [(change, _unwritten(change)) for change in plan.update if _unwritten(change)]
    return Prepared(path, len(entries), plan, routes, closes, drift, problems)


def created_of(entry):
    """The ledger's date as a timestamp, or `None` for an entry that has none."""
    return f"{entry.date}T00:00:00Z" if entry.date else None


def apply(root, prepared):
    """Write the plan. Returns `(lines, problems)`. Refuses outright on a plan with problems."""
    if prepared.problems:
        return [], ["the plan has problems, so nothing was written"]
    lines, problems = [], []
    for entry, to in zip(prepared.plan.create, prepared.routes):
        record, problem = handoffs.post(
            root,
            to,
            reconcile.body_of(entry),
            cwd=str(root),
            name=entry.sender,
            at=created_of(entry),
            imported=reconcile.imported_of(entry),
        )
        if problem:
            problems.append(problem)
        else:
            lines.append(f"posted  {record['id']}  {store.printable(entry.headline[:60])}")
    for change in prepared.closes:
        handoff_id = change.record["id"]
        _, problem = handoffs.set_status(
            root, handoff_id, handoffs.CLOSED, by=BY, note="closed in the ledger"
        )
        if problem:
            problems.append(problem)
        else:
            lines.append(f"closed  {handoff_id}")
    return lines, problems


def outstanding(prepared):
    """What an import still has to do, as a count. Zero with no problems is step 4 done."""
    return len(prepared.plan.create) + len(prepared.closes)
