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

**The id comes from the key, not from the clock.** Two sessions told by `doctor` to run this at the
same moment would otherwise each post every entry, and the pair would block every later run as two
rows sharing a key, with no verb that removes either. Derived from the key, the second post lands on
a name the first already took, and `create_json` refuses it at the filesystem.

**An imported row that is open with no entry left is outstanding.** An entry deleted from the
ledger, or one whose key changed under it (a date added, a sender renamed), leaves its stored copy
open with nothing to close it. Nothing here can tell which entry it became, so nothing is written,
but `doctor` does not call the step done while one is there: the store would say a handoff is
waiting that the ledger has finished with. The key includes the ledger's own labels, so pointing
`legacy_ledger` at a different file or section after an import strands every open row from the old
one, which is the right reading: nothing will close them from there either.

**`created` is the ledger's date, not the import's.** Staleness is read off `created`, and an entry
nine days old imported today would otherwise read as fresh, which is the ten-day silent failure this
project started from arriving by a new route. An undated entry gets the time of the import, and that
is the one place it has to be said, so it is said in the report.
"""

from __future__ import annotations

import hashlib
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
    both. `stranded` are the orphans still open, which nothing here can close.
    """

    path: pathlib.Path
    parsed: int
    plan: reconcile.Plan
    routes: list[dict[str, Any]]
    closes: list[reconcile.Change]
    drift: list[tuple[reconcile.Change, dict[str, tuple[Any, Any]]]]
    stranded: list[dict[str, Any]]
    problems: list[str]


def ledger_path(root, block):
    """The ledger file named by `legacy_ledger.path`, relative to the root unless absolute."""
    path = pathlib.Path(block["path"]).expanduser()
    return path if path.is_absolute() else pathlib.Path(root) / path


def route_label(label):
    """A route key from the marker, in the form `route_of` looks it up by.

    A group is sorted the way `reconcile.route_key` sorts recipients, so `Lane G + Lane B` written
    as the ledger writes it finds the entry addressed that way.
    """
    parts = [ledger.normalise_label(part) for part in label.split(reconcile.RECIPIENT_JOIN)]
    return reconcile.RECIPIENT_JOIN.join(sorted(part for part in parts if part))


def route_table(block):
    """`(table, problems)`. Two keys that normalise alike are a problem, not a last-wins."""
    table, problems = {}, []
    for label, scope in block.get("routes", {}).items():
        key = route_label(label)
        if not key:
            problems.append(f"legacy_ledger.routes has an empty label ({store.printable(label)!r})")
        elif key in table:
            problems.append(f"legacy_ledger.routes names {key!r} twice, in different spellings")
        else:
            table[key] = scope
    return table, problems


def route_of(entry, table):
    """The `to` block for one entry, or `(None, problem)`."""
    if not entry.recipients:
        return None, f"no recipient to route to ({store.printable(entry.headline[:60])!r})"
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
    to, fault = handoffs.to_scope(repo=scope.get("repo"), paths=scope.get("paths", ()))
    if fault:
        return None, f"the route for {group!r} in legacy_ledger.routes: {fault}"
    return to, None


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
        fault = f"cannot read {path}: {type(exc).__name__}"
        return Prepared(path, 0, empty, [], [], [], [], [fault])
    section = block.get("section", ledger.DEFAULT_SECTION)
    entries, problem = ledger.entries(text, section)
    if problem and not _emptied(text, section):
        return Prepared(path, 0, empty, [], [], [], [], [problem])
    held, problems = handoffs.load_all(root)
    plan = reconcile.reconcile(entries, held)
    table, route_problems = route_table(block)
    problems = [*problems, *plan.problems, *route_problems]
    routes = []
    for entry in plan.create:
        scope, fault = route_of(entry, table)
        if fault:
            problems.append(fault)
        routes.append(scope)
    closes = [change for change in plan.update if _is_close(change)]
    drift = [(change, _unwritten(change)) for change in plan.update if _unwritten(change)]
    status = {record["id"]: state for record, state in held}
    stranded = [record for record in plan.orphan if status.get(record["id"]) != handoffs.CLOSED]
    return Prepared(path, len(entries), plan, routes, closes, drift, stranded, problems)


def _emptied(text, section):
    """Whether the section is there and blank, which is where a pruned ledger ends up.

    Not a problem then: blocking forever on the end state of the dual run would be the wrong way
    round. The rows it held are orphans by now, and an open one is still reported as stranded.
    Blank and not merely entry-less, because a section with text in it and no entry the parser
    recognises is the silent short count `ledger` exists to refuse.
    """
    wanted = ledger.normalise_label(section)
    bodies = [
        body
        for title, body in ledger.sections(text)
        if ledger.normalise_label(title).startswith(wanted)
    ]
    # Every matching heading, not any: a blank archive must not excuse prose in the real one.
    return bool(bodies) and not any(body.strip() for body in bodies)


def id_of(entry):
    """The id an imported entry is posted under, the same on every run and every machine."""
    key = json.dumps(reconcile.imported_of(entry), sort_keys=True)
    stamp = entry.date.replace("-", "") + "T000000Z" if entry.date else "undated"
    return f"{stamp}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def created_of(entry):
    """The ledger's date as a timestamp, or `None` for an entry that has none."""
    return f"{entry.date}T00:00:00Z" if entry.date else None


def apply(root, prepared):
    """Write the plan. Returns `(lines, problems)`. Refuses outright on a plan with problems."""
    if prepared.problems:
        return [], ["the plan has problems, so nothing was written"]
    lines, problems = [], []
    for entry, to in zip(prepared.plan.create, prepared.routes):
        handoff_id = id_of(entry)
        moves = store.transitions_dir(root, handoff_id)
        if moves.exists():
            # Left behind when a closed import's record was removed by hand. The id is derived from
            # the ledger entry, so every run would post under it again and be refused the same way,
            # and "run it again" never ends. Only the person can say the directory is stale.
            problems.append(
                f"{handoff_id} has moves recorded at {moves}, left behind after its record was "
                f"removed; move that directory aside, then run it again"
            )
            continue
        record, problem = handoffs.post(
            root,
            to,
            reconcile.body_of(entry),
            cwd=str(root),
            name=entry.sender,
            handoff_id=handoff_id,
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
    if problems:
        done = len(lines)
        total = len(prepared.plan.create) + len(prepared.closes)
        problems.append(f"{done} of {total} write(s) made; run it again to finish the rest")
    return lines, problems


def outstanding(prepared):
    """What an import still has to do, as a count. Zero with no problems is step 4 done."""
    return len(prepared.plan.create) + len(prepared.closes) + len(prepared.stranded)
