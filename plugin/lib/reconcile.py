"""The importer's key, and reconciling a ledger parse against what is already stored.

`ledger.py` reads the file and stops. This module answers the one question that decides whether an
import is safe to run twice: which of these entries is a row that already exists. Nothing here
writes; the write path is the next step.

The key is `(route, original headline prefix, date or none)` and every part of that was arrived at
by elimination:

**Not a hash of the entry text.** The source convention has the recipient acknowledge *in place*,
rewriting the headline and pushing the original behind a `Was:` marker. So the text changes while
the identity does not. A hash key is idempotent under the operation that does not matter -
re-importing an untouched file - and duplicates under the only one that does, leaving the stale
row beside the new one still marked open. Wrong state, and not visibly wrong.

**Not `(route, date)` either.** Nine collisions across the 45 historical records: two handoffs
between the same pair on the same day is ordinary. The live file's uniqueness was sample size, not
a property of the format.

**The original headline is the discriminator, and it survives acknowledgement by construction**,
because preserving it verbatim is the entire point of the convention. `ledger.Entry` already reads
it from the whole block rather than the header line, which is the case that wraps.

**The date is compared strictly, with absence as a value.** A loose match - "equal, or either side
absent" - was written first and thrown away: it is not transitive, so an undated entry sitting
between two dated ones matches both and the dedupe's answer depends on iteration order. Strict and
hashable instead, which means an undated entry later given a date re-keys. That is a duplicate,
and a duplicate is visible; a non-transitive match is not.

**The headline is compared on a prefix, and it errs long.** The reason for a prefix at all is that
a typo fix in the preserved original should not re-key. The reason it is 64 characters and not 20
is the asymmetry this whole project runs on: a prefix too short merges two distinct handoffs,
which *loses* one silently, and a prefix too long splits one into two, which is noise a reader can
see. Guess towards showing. The residual risk is handled rather than accepted: two entries in the
same import that key the same are reported as a problem, so the merge case cannot happen quietly.

**A problem means do not write.** `reconcile` returns problems rather than raising or guessing,
because the states it reports - two entries it cannot tell apart, two stored rows sharing a key -
are exactly the ones where guessing produces the wrong state invisibly. The write path refuses on
a non-empty `problems`; a human disambiguates the source.

**Closed entries that were never imported are skipped, and counted.** The step imports open
handoffs; a closed one has nothing to surface. Counted rather than filtered out beforehand,
because "10 entries parsed, 5 imported" reads as a parse failure unless something says the other
five were closed.

**Rows stored with no `imported` block are not this module's business at all.** They were posted
natively. An importer that touched them, or reported them as orphans, would be claiming ownership of
state it did not create.
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Any, NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ledger

# Long enough that two distinct handoffs on one route agreeing for this many characters is not a
# case worth designing for, short enough to absorb an edit to the tail. Unmeasured, unlike the
# constants in `ledger.py`, and deliberately so: the corpus that would measure it is not readable
# from here. Two things make the number safe to be wrong about: the collision report below, and a
# pair of checks pinning it from either side, which exist because the mutation sweep found it free
# to be any value at all.
HEADLINE_PREFIX = 64

# Written between the two halves of the route instead of an arrow. The source spells the arrow two
# ways and writes one of them backwards, and the direction is already resolved by the time a key is
# built, so keeping a glyph here would only reintroduce a spelling to get wrong.
ROUTE_JOIN = ">"

# Recipients within one side, joined after sorting. `A + B` and `B + A` are the same route: the
# order recipients are typed in carries nothing.
RECIPIENT_JOIN = "+"

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"


class Key(NamedTuple):
    """A `NamedTuple` so it is hashable and compares by value, which is the whole requirement."""

    route: str
    headline: str
    date: str | None


class Change(NamedTuple):
    """A matched pair, and the fields on which the stored row disagrees with the ledger.

    `fields` empty is impossible here - an unchanged match goes in `Plan.unchanged` instead - so a
    caller reading this never has to ask whether an update is a no-op.
    """

    entry: ledger.Entry
    record: dict[str, Any]
    fields: dict[str, tuple[Any, Any]]


class Plan(NamedTuple):
    """What an import would do, with nothing done.

    Six lists rather than two, because every one of them is a number that should be looked at. An
    importer reporting only "created 5" hides the four cases that matter: rows it decided not to
    touch, rows it could not find a source for, entries it skipped, and pairs it could not tell
    apart.
    """

    create: list[ledger.Entry]
    update: list[Change]
    unchanged: list[ledger.Entry]
    skipped: list[ledger.Entry]
    orphan: list[dict[str, Any]]
    problems: list[str]


def route_key(sender: str | None, recipients: list[str]) -> str:
    """The route, in a form two spellings of it compare equal in.

    Built from `sender` and `recipients` rather than from `Entry.route`, because the parser has
    already resolved direction there: shape B is rewritten into shape A's order and a reversed
    arrow is swapped. Normalising the raw route string instead would mean re-deriving direction,
    in a second place, from the two arrow spellings the source uses - which is the drift this
    project exists to remove.

    An absent sender is a legitimate value, not a failure: one measured shape addresses an entry
    to a label with no arrow at all, and that label is the recipient.
    """
    left = ledger.normalise_label(sender) if sender else ""
    right = RECIPIENT_JOIN.join(sorted(ledger.normalise_label(part) for part in recipients))
    return f"{left}{ROUTE_JOIN}{right}"


def headline_key(headline: str) -> str:
    """The headline folded to its comparable prefix.

    The parser has already stripped emphasis and the header separator, so this only folds case and
    whitespace. Deliberately no punctuation stripping: that would be guessing at which edits are
    cosmetic, and the prefix is already the mechanism for absorbing an edit.

    Stripped *after* truncating, not only before, and that ordering is the whole function. Cut at
    a fixed length and two of the census entries land the cut on a space; normalising the stored
    value on the way back in then strips it, the key comes out one character shorter than the one
    that was written, and the row no longer matches its own source. It re-imports as a create and
    the original reports as an orphan, which is the duplicate-row failure this key exists to
    prevent, arriving through the back door. This has to be idempotent, and there is a check
    asserting it is.
    """
    folded = re.sub(r"\s+", " ", headline).strip().casefold()
    return folded[:HEADLINE_PREFIX].strip()


def key_of(entry: ledger.Entry) -> Key | None:
    """The entry's key, or `None` when it has no route to key on.

    A routeless entry is not dropped quietly - `reconcile` turns this `None` into a problem naming
    the headline. An entry addressed to nobody cannot be delivered to anybody, and inventing a
    route for it would make the next import find a row nothing in the file corresponds to.
    """
    route = route_key(entry.sender, entry.recipients)
    if route.strip(ROUTE_JOIN + " ") == "":
        return None
    return Key(route, headline_key(entry.original_headline), entry.date)


def key_of_record(record: dict[str, Any]) -> Key | None:
    """The stored row's key, or `None` if it was not imported from a ledger.

    The stored values are re-normalised rather than trusted. That is idempotent for anything this
    code wrote, and the file is hand-editable, so the alternative is a row that silently stops
    matching its own source because somebody fixed its capitalisation.

    A block present but missing either half reads as not imported, which is the safe direction: the
    schema requires both, so a row like that never reached the store through the validator.
    """
    imported = record.get("imported")
    if not isinstance(imported, dict):
        return None
    route = imported.get("route")
    headline = imported.get("headline")
    if not route or not headline:
        return None
    left, _, right = route.partition(ROUTE_JOIN)
    recipients = [part for part in right.split(RECIPIENT_JOIN) if part]
    return Key(route_key(left or None, recipients), headline_key(headline), imported.get("date"))


def imported_of(entry: ledger.Entry) -> dict[str, str]:
    """The `imported` block the schema requires, which is the key written down.

    `date` is omitted rather than stored as null, because the schema constrains its shape and an
    absent date is the absence of a fact, not a fact about absence.
    """
    key = key_of(entry)
    if key is None:
        raise ValueError("an entry with no route has no key to store")
    block = {"route": key.route, "headline": key.headline}
    if key.date:
        block["date"] = key.date
    return block


def status_of(entry: ledger.Entry) -> str:
    """`open` or `closed`, and never `accepted`.

    The schema has three states and this maps to two, which is a narrowing worth stating. Closure
    is the one the parser reads from measured positions with both over-match guards on it.
    Acceptance has no equivalent: the nearest signal is `Entry.status`, a field documented as
    display-only and truncated for width, so keying real state off it would be reading a label
    meant for a human. An imported row therefore arrives open or closed, and acceptance is
    something a session does to it afterwards through the normal path.
    """
    return STATUS_CLOSED if entry.closed else STATUS_OPEN


def body_of(entry: ledger.Entry) -> str:
    """The entry's own markdown, verbatim.

    Verbatim because the schema promises nothing parses a body for structure, and because this is
    the field that changes when a recipient acknowledges in place - which is what makes that
    operation an update rather than a no-op.

    The ends are trimmed and the inside is not, which is a deliberate asymmetry rather than a
    half-finished one: two trailing spaces are a markdown hard line break, so folding whitespace
    anywhere but the very end would quietly change what the body means on its way into the store.
    The cost is that a stray space mid-block reports as a change on a run where nothing happened.
    Noise a reader can see, against a body silently rewritten - the same trade as everywhere else
    here.
    """
    return entry.block.strip()


def changes(entry: ledger.Entry, record: dict[str, Any], status: str) -> dict[str, tuple[Any, Any]]:
    """Which of the importer's own fields the stored row disagrees with, as `(stored, ledger)`.

    Only the fields an import writes. A row moved in the store through the normal path is not in
    disagreement about anything an import owns, except status, which the ledger is the source of
    truth for as long as the ledger is still being written to.

    `status` is passed in rather than read off the record, because since #44 it is not on the
    record: it is derived from the moves in `handoffs/<id>.d/`, and `handoffs.load_all` is what
    pairs the two. Taking it as an argument keeps this module pure - no clock, no filesystem -
    which is what makes it testable without a store at all.
    """
    out = {}
    # A dict rather than two `record.get` calls, because `status` no longer comes from the record
    # and a reader should not have to remember which of the two fields does.
    held = {"status": status, "body": record.get("body")}
    for field, value in (("status", status_of(entry)), ("body", body_of(entry))):
        if held[field] != value:
            out[field] = (held[field], value)
    stored = record.get("imported")
    fresh = imported_of(entry)
    if stored != fresh:
        out["imported"] = (stored, fresh)
    return out


def _by_key(items: list[Any], keyer: Any, what: str) -> tuple[dict[Key, Any], list[str], list[Any]]:
    """Index by key, reporting anything that collides or cannot be keyed rather than dropping it."""
    grouped: dict[Key, list[Any]] = {}
    unkeyed = []
    for item in items:
        key = keyer(item)
        if key is None:
            unkeyed.append(item)
            continue
        grouped.setdefault(key, []).append(item)
    problems = []
    index = {}
    for key, group in grouped.items():
        if len(group) > 1:
            problems.append(f"{len(group)} {what} share the key {key.route} / {key.headline!r}")
        index[key] = group[0]
    return index, problems, unkeyed


def reconcile(entries: list[ledger.Entry], held: list[tuple[dict[str, Any], str]]) -> Plan:
    """What importing `entries` over `held` would do.

    `held` is what `handoffs.load_all` returns: each stored row paired with the status derived from
    its moves. A pair rather than a record, because since #44 a record has no status in it, and this
    module compares status.

    Pure: no clock, no filesystem, no ordering assumption. The source is not in date order and never
    was, so nothing here may infer position from a date or the reverse.
    """
    source, problems, unkeyed = _by_key(entries, key_of, "ledger entries")
    for entry in unkeyed:
        problems.append(f"no route to key on: {entry.headline[:60]!r}")
    stored, stored_problems, _ = _by_key(held, lambda pair: key_of_record(pair[0]), "stored rows")
    problems.extend(stored_problems)

    create, update, unchanged, skipped = [], [], [], []
    for key, entry in source.items():
        pair = stored.get(key)
        if pair is None:
            # Closed and never imported: nothing to surface, but counted rather than dropped.
            if entry.closed:
                skipped.append(entry)
            else:
                create.append(entry)
            continue
        record, status = pair
        fields = changes(entry, record, status)
        if fields:
            update.append(Change(entry, record, fields))
        else:
            unchanged.append(entry)
    orphan = [record for key, (record, _) in stored.items() if key not in source]
    return Plan(create, update, unchanged, skipped, orphan, problems)
