#!/usr/bin/env python3
"""The importer's key and its dedupe, against the operation that breaks a naive one.

The gate that matters is third from the top: import, acknowledge one entry the way the source
convention says to, import again. A correct key updates one row and creates none. A content hash
goes green on the unchanged-file case, which is the question that never occurs in practice, and
duplicates on the only one that does. So the acknowledgement here is performed rather than
snapshotted - the test edits the fixture text the way a recipient edits the file - and the edit is
asserted to have actually changed the parse before its effect on the key is asserted at all. A
fixture that no longer exercises the case it was written for is this project's recurring failure
and it is invisible from the output.

Everything else follows CONTRIBUTING: each rule is asserted next to the case that breaks it, and the
negative is asserted on content that is present rather than by omission, so deleting a rule fails a
named check instead of changing a count nobody reads.
"""

import os.path
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import ledger
import reconcile
import validate

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
CENSUS = (FIXTURES / "handoffs.md").read_text()
SHAPES = (FIXTURES / "ledger-shapes.md").read_text()

SECTION = "## Open questions / handoffs\n\n"

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def entry_with(text, fragment):
    """The one entry in `text` whose headline or preserved original contains `fragment`.

    By content rather than by index, so inserting a case does not renumber every assertion after it.
    """
    rows, problem = ledger.entries(text)
    if problem:
        print(f"  FAIL  parsing for {fragment!r}: {problem}")
        failures.append(f"parse {fragment!r}")
        return None
    found = [r for r in rows if fragment in r.headline or fragment in r.original_headline]
    if len(found) != 1:
        print(f"  FAIL  lookup {fragment!r} matched {len(found)} entries, want 1")
        failures.append(f"lookup {fragment!r}")
        return None
    return found[0]


def record_of(entry, ident="h"):
    """A stored row as the write path would write one, standing in for a write path that does not
    exist yet.

    Deliberately assembled here rather than in `reconcile`: this PR keys and dedupes, and a record
    builder living in the library would be the write path arriving early and untested. The three
    fields the dedupe actually reads - `status`, `body`, `imported` - come from the library, so the
    test cannot accidentally agree with itself about them.
    """
    return {
        "id": ident,
        "from": {"cwd": "/tmp/somewhere"},
        "to": {"repo": "somewhere"},
        "created": "2026-01-01T00:00:00Z",
        "status": reconcile.status_of(entry),
        "body": reconcile.body_of(entry),
        "imported": reconcile.imported_of(entry),
    }


def records_of(text):
    rows, _ = ledger.entries(text)
    return [record_of(row, f"h{n}") for n, row in enumerate(rows) if not row.closed]


print("a first import of the census fixture")

census, _ = ledger.entries(CENSUS)
first = reconcile.reconcile(census, [])

check("no problems on a file that parses", first.problems, [])
check("the five open entries are created", len(first.create), 5)
check("the five closed ones are skipped, not created", len(first.skipped), 5)
check("and skipped is counted rather than filtered out beforehand", len(census), 10)
check("nothing to update against an empty store", (first.update, first.unchanged), ([], []))
check("and no orphans, because there is nothing stored to orphan", first.orphan, [])

print()
print("a second import of the same file, which is the case a hash key also passes")

stored = records_of(CENSUS)
again = reconcile.reconcile(census, stored)

check("creates nothing the second time", again.create, [])
check("and updates nothing either, because nothing differs", again.update, [])
check("the five open rows are recognised as unchanged", len(again.unchanged), 5)
check("the closed ones are still skipped, not resurrected", len(again.skipped), 5)
check("and no row is orphaned by a run that changed nothing", again.orphan, [])

print()
print("acknowledgement in place, which is the case a hash key fails")

# The documented convention, performed rather than snapshotted: the status clause goes in at the
# front of the headline's bold run, and the original headline is pushed to the right of a literal
# `Was:` on the same physical line and left verbatim. Route and date are untouched, which is
# measured: the closure date is written after the entry's own so the original stays the first date
# in the header.
BEFORE_OPEN = "— **canonical shape,"
AFTER_OPEN = "— **ACCEPTED by Lane B 2026-01-20, picking it up now. Was: canonical shape,"
BEFORE_MARKER = "the same line.** **Status:** OPEN"
AFTER_MARKER = "the same line.** **Status:** ACCEPTED"

check("the text the edit replaces is there to replace", CENSUS.count(BEFORE_OPEN), 1)
check("and so is the status marker it moves", CENSUS.count(BEFORE_MARKER), 1)
acknowledged = CENSUS.replace(BEFORE_OPEN, AFTER_OPEN).replace(BEFORE_MARKER, AFTER_MARKER)
check("the edit changed the file", acknowledged != CENSUS, True)

was_open = entry_with(CENSUS, "canonical shape")
now_acked = entry_with(acknowledged, "canonical shape")

# Asserted before anything about keys, because a gate whose fixture stopped exercising its case
# reads exactly like a gate that passes.
check(
    "the headline on the page is now the recipient's rewrite",
    now_acked.headline,
    "ACCEPTED by Lane B 2026-01-20, picking it up now",
)
check("so the current headline did change", now_acked.headline == was_open.headline, False)
check(
    "and the original is preserved behind the marker, verbatim",
    now_acked.original_headline,
    was_open.original_headline,
)
check("the route survives untouched", now_acked.route, was_open.route)
check("and so does the entry's own date, ahead of the closure date", now_acked.date, "2026-01-02")

check("which is why the key is unchanged", reconcile.key_of(now_acked), reconcile.key_of(was_open))
# The deliberate break, in one line: the entry's text is what a hash would key on, and it moved.
check(
    "while the text a hash would key on is not",
    reconcile.body_of(now_acked) == reconcile.body_of(was_open),
    False,
)

acked_rows, _ = ledger.entries(acknowledged)
after = reconcile.reconcile(acked_rows, stored)

check("so the import updates exactly one row", len(after.update), 1)
check("and creates none, which is the whole gate", after.create, [])
check("the other four open rows are untouched", len(after.unchanged), 4)
check("no row is orphaned, because the entry is still there", after.orphan, [])
check("the updated row is the one that was acknowledged", after.update[0].entry.date, "2026-01-02")
check("and it is the body that differs", sorted(after.update[0].fields), ["body"])
check(
    "not the status, because accepting is not closing and nothing here reads acceptance",
    reconcile.status_of(now_acked),
    "open",
)

print()
print("closure in the ledger after the import, which has to reach the stored row")

# The mutation sweep found this missing: with the body compared and the status not, every gate
# above still passed, and an entry closed in the source would have stayed open in the store
# forever. That is the exact failure mode this project exists to remove, so it is asserted here
# rather than assumed to follow from the body comparison.
BEFORE_TRAP = "in the entry.** Added 2026-09-25"
closed_later = CENSUS.replace(
    BEFORE_TRAP, "in the entry.** **Status:** DONE 2026-03-07 Added 2026-09-25"
)
check("the closure was written in", CENSUS.count(BEFORE_TRAP), 1)

trap_open = entry_with(CENSUS, "prose closure trap")
trap_closed = entry_with(closed_later, "prose closure trap")
check("the entry was open", trap_open.closed, False)
check("and is now closed", trap_closed.closed, True)
check(
    "with the key untouched, because the prefix is what absorbed the edit",
    reconcile.key_of(trap_closed),
    reconcile.key_of(trap_open),
)

closure = reconcile.reconcile(ledger.entries(closed_later)[0], stored)
check("the stored row updates rather than duplicating", len(closure.update), 1)
check("and the status is one of the fields that moved", "status" in closure.update[0].fields, True)
check("from open to closed", closure.update[0].fields["status"], ("open", "closed"))
check(
    "it is not skipped, because skipping is only for a closure never imported",
    len(closure.skipped),
    5,
)

print()
print("two handoffs on one route on one day, which is why (route, date) is not the key")

SAME_DAY = SECTION + (
    "**[Lane A → Lane B]** 2026-03-01 — **the first of two between one pair on one day, which the "
    "measurement says is ordinary rather than exceptional.** **Status:** OPEN\n\n"
    "**[Lane A → Lane B]** 2026-03-01 — **the second, which a route-and-date key folds into the "
    "first and reports as one import.** **Status:** OPEN\n"
)

same_day, same_day_problem = ledger.entries(SAME_DAY)
check("both parse", (len(same_day), same_day_problem), (2, None))
check("their routes are identical", same_day[0].route, same_day[1].route)
check("so are their dates", same_day[0].date, same_day[1].date)
check(
    "and the headline is the only thing separating them",
    reconcile.key_of(same_day[0]) == reconcile.key_of(same_day[1]),
    False,
)

same_day_plan = reconcile.reconcile(same_day, [])
check("they import as two", len(same_day_plan.create), 2)
check(
    "with nothing reported, because there is nothing ambiguous about them",
    same_day_plan.problems,
    [],
)

print()
print("the prefix's own cost, reported rather than accepted")

SHARED = "an opening clause long enough to fill the whole of the compared prefix and then some"
check("the shared clause does fill the prefix", len(SHARED) >= reconcile.HEADLINE_PREFIX, True)

COLLIDING = SECTION + (
    f"**[Lane A → Lane B]** 2026-03-02 — **{SHARED}, and then this one diverges.** "
    "**Status:** OPEN\n\n"
    f"**[Lane A → Lane B]** 2026-03-02 — **{SHARED}, but this one says something else "
    "entirely.** **Status:** OPEN\n"
)

colliding, _ = ledger.entries(COLLIDING)
check("two entries, and they are genuinely different asks", len(colliding), 2)
check("but they key the same", reconcile.key_of(colliding[0]), reconcile.key_of(colliding[1]))

collided = reconcile.reconcile(colliding, [])
check("so one of them would be lost silently", len(collided.create), 1)
check("which is why it is reported instead", len(collided.problems), 1)
check(
    "and the report names the key, not just a count",
    "share the key" in collided.problems[0] and "lane a>lane b" in collided.problems[0],
    True,
)

# The length itself, pinned from both sides. The sweep found it free to be any value: shortening
# it to 20 broke nothing, which means nothing was asserting what the number buys.
NEAR = (
    "the same opening words for a good while, and then they diverge",
    "the same opening words for a good while, but here they do not",
)
common = len(os.path.commonprefix(NEAR))
check("the pair shares a long opening", common >= 32, True)
check("and diverges inside the compared prefix", common < reconcile.HEADLINE_PREFIX, True)
check(
    "so a prefix short enough to miss the divergence would merge them, and this one does not",
    reconcile.headline_key(NEAR[0]) == reconcile.headline_key(NEAR[1]),
    False,
)

# And from above: absorbing an edit past the prefix is the reason there is a prefix at all.
tail_edited = CENSUS.replace("the same line.**", "the same line, with a clause added afterwards.**")
check("the tail edit landed past the prefix", tail_edited != CENSUS, True)
edited_entry = entry_with(tail_edited, "canonical shape")
check(
    "it did lengthen the headline",
    len(edited_entry.original_headline) > len(was_open.original_headline),
    True,
)
check("and the key is unchanged", reconcile.key_of(edited_entry), reconcile.key_of(was_open))
tail = reconcile.reconcile(ledger.entries(tail_edited)[0], stored)
check(
    "so a later edit to the tail updates rather than duplicating",
    (len(tail.update), tail.create),
    (1, []),
)

# Case, which the sweep also found untested. The stored headline is a key and not a display value,
# so folding costs nothing and buys a row that survives someone tidying capitalisation.
recased = CENSUS.replace(
    "**canonical shape, and the majority", "**Canonical Shape, And The Majority"
)
check("the recapitalisation landed", recased != CENSUS, True)
check(
    "and the key is unchanged",
    reconcile.key_of(entry_with(recased, "Canonical Shape")),
    reconcile.key_of(was_open),
)
check(
    "so tidying capitalisation does not duplicate the row",
    reconcile.reconcile(ledger.entries(recased)[0], stored).create,
    [],
)

print()
print("an entry with nothing to key on")

NOBODY = SECTION + "**[]** 2026-03-03 — **addressed to nobody at all.** **Status:** OPEN\n"
nobody, _ = ledger.entries(NOBODY)
check("it parses as an entry", len(nobody), 1)
check("with no sender and no recipient", (nobody[0].sender, nobody[0].recipients), (None, []))
check("so it has no key", reconcile.key_of(nobody[0]), None)

nobody_plan = reconcile.reconcile(nobody, [])
check("it is not created", nobody_plan.create, [])
check("and not dropped quietly either", len(nobody_plan.problems), 1)
check("the problem names the headline", "addressed to nobody" in nobody_plan.problems[0], True)

print()
print("the route key, where two spellings have to meet")

forward = entry_with(
    SECTION + "**[Lane E → Lane F]** 2026-02-04 — **written forwards.** **Status:** OPEN\n",
    "written forwards",
)
backward = entry_with(SHAPES, "reversed arrow")
check(
    "a reversed arrow keys the same as the forward spelling",
    reconcile.route_key(backward.sender, backward.recipients),
    reconcile.route_key(forward.sender, forward.recipients),
)

# Through `key_of` rather than only through `route_key`, which the sweep showed was the difference
# between asserting the rule and asserting a helper: keying off the raw route field instead of the
# resolved pair passes every check that calls the helper directly, and duplicates the row here.
PAIR = "one handoff, written two ways round"
FORWARD = SECTION + f"**[Lane E → Lane F]** 2026-02-04 — **{PAIR}.** **Status:** OPEN\n"
BACKWARD = SECTION + f"**[Lane F ← Lane E]** 2026-02-04 — **{PAIR}.** **Status:** OPEN\n"
both_ways = reconcile.reconcile(
    ledger.entries(BACKWARD)[0], [record_of(ledger.entries(FORWARD)[0][0])]
)
check("so the same handoff written backwards is the same row", both_ways.create, [])
check("and shows up as one update, not a second handoff", len(both_ways.update), 1)

check(
    "whitespace around a slash is folded on both sides of the route",
    reconcile.route_key("Lane C / D", ["Lane E/F"]),
    reconcile.route_key("Lane C/D", ["Lane E / F"]),
)
check(
    "recipient order carries nothing",
    reconcile.route_key("Lane A", ["Lane B", "Lane C"]),
    reconcile.route_key("Lane A", ["Lane C", "Lane B"]),
)
check(
    "an absent sender is a value, not a failure",
    reconcile.route_key(None, ["Lane B"]),
    ">lane b",
)
check(
    "and two different pairs do not collapse",
    reconcile.route_key("Lane A", ["Lane B"]) == reconcile.route_key("Lane B", ["Lane A"]),
    False,
)

print()
print("the key written down, and read back")

dated = entry_with(CENSUS, "three variations in one header")
check(
    "the stored block is the key, with the date",
    reconcile.imported_of(dated),
    {
        "route": "lane c/d>lane e/f",
        "headline": reconcile.key_of(dated).headline,
        "date": "2026-01-03",
    },
)
check(
    "reading it back gives the same key, which is what makes a second import idempotent",
    reconcile.key_of_record(record_of(dated)),
    reconcile.key_of(dated),
)

# The generalised version of a bug this found. Two census headlines are long enough that the
# prefix cuts on a space, and stripping only before the cut left the stored key one character
# shorter than the one that produced it: both rows re-imported as creates while their originals
# reported as orphans. Asserted as a property over the whole fixture rather than on the two
# entries that happened to trip it, because the next headline to land on the boundary will not be
# either of them.
check(
    "keying a stored key again changes nothing, for every entry in the census",
    [
        r.date
        for r in census
        if reconcile.headline_key(reconcile.headline_key(r.original_headline))
        != reconcile.headline_key(r.original_headline)
    ],
    [],
)
check(
    "so every stored row reads back to the key that wrote it",
    [
        r.date
        for r in census
        if not r.closed and reconcile.key_of_record(record_of(r)) != reconcile.key_of(r)
    ],
    [],
)

undated = entry_with(SHAPES, "undated: no date anywhere")
check(
    "an undated entry omits the field rather than storing a null",
    "date" in reconcile.imported_of(undated),
    False,
)
check("and still keys", reconcile.key_of(undated) is None, False)
check(
    "and reconciles against its own row without faulting",
    len(reconcile.reconcile([undated], [record_of(undated)]).unchanged),
    1,
)

try:
    reconcile.imported_of(nobody[0])
    raised = None
except ValueError as problem:
    raised = str(problem)
check(
    "a routeless entry refuses to be stored rather than storing a meaningless key",
    raised is None,
    False,
)

print()
print("a hand-edited store, and rows the importer does not own")

hand_edited = dict(
    record_of(dated),
    imported={
        "route": "LANE C / D > Lane E/F",
        "headline": reconcile.key_of(dated).headline.upper(),
        "date": "2026-01-03",
    },
)
check(
    "capitalisation and spacing in a stored key still match their source",
    reconcile.key_of_record(hand_edited),
    reconcile.key_of(dated),
)
check(
    "and the difference is reported, so the row gets rewritten into normal form",
    sorted(reconcile.changes(dated, hand_edited)),
    ["imported"],
)

# The state a hash-keyed importer leaves behind: the same handoff stored twice, the stale copy still
# open. It cannot be repaired by a better key alone, so it has to be said out loud.
doubled = reconcile.reconcile(census, [*stored, dict(record_of(dated), id="h-again")])
check(
    "two stored rows sharing a key are reported, not silently picked between",
    [p for p in doubled.problems if "stored rows" in p],
    ["2 stored rows share the key lane c/d>lane e/f / " + repr(reconcile.key_of(dated).headline)],
)

# Whitespace at the end of a block is not an edit, and whitespace inside one is. The asymmetry is
# deliberate: two trailing spaces are a markdown hard line break, so folding them anywhere but the
# very end would rewrite what the body means on the way into the store. Reporting a spurious update
# is noise a reader can see; quietly altering a body is not.
ONE = SECTION + "**[Lane A → Lane B]** 2026-03-06 — **a single-line entry.** **Status:** OPEN\n"
plain = ledger.entries(ONE)[0]
padded = ledger.entries(ONE.replace("OPEN\n", "OPEN   \n"))[0]
check("the padding landed in the block", padded[0].block.endswith("   "), True)
check("but not in the body", reconcile.body_of(padded[0]), reconcile.body_of(plain[0]))
check(
    "so a file touched only by a stray space at the end updates nothing",
    reconcile.reconcile(padded, [record_of(plain[0])]).update,
    [],
)

inner = CENSUS.replace(BEFORE_MARKER, BEFORE_MARKER + "   ")
check("the interior padding landed", inner != CENSUS, True)
check(
    "and is reported as a change, because eating it would rewrite a hard line break",
    len(reconcile.reconcile(ledger.entries(inner)[0], stored).update),
    1,
)

native = {
    "id": "posted-by-a-session",
    "from": {"cwd": "/tmp/somewhere", "session_id": "abc-123"},
    "to": {"repo": "somewhere"},
    "created": "2026-03-05T00:00:00Z",
    "status": "open",
    "body": "posted through the normal path, never imported from anything",
}
check("a natively posted row has no importer key", reconcile.key_of_record(native), None)
native_plan = reconcile.reconcile(census, [*stored, native])
check("so the importer does not orphan it", native_plan.orphan, [])
check("does not update it", len(native_plan.update), 0)
check("and does not report it as a problem", native_plan.problems, [])

print()
print("a row whose source is gone, and a date that appears later")

gone = record_of(entry_with(SHAPES, "reversed arrow"), "from-another-file")
orphaned = reconcile.reconcile(census, [*stored, gone])
check("a stored row with no live entry is reported", len(orphaned.orphan), 1)
check("named, so it can be looked at", orphaned.orphan[0]["id"], "from-another-file")
check("and not touched: the archive is a different format, not a deletion", orphaned.update, [])

# The known cost of comparing the date strictly, pinned rather than left to be discovered. A loose
# match would absorb this and is not transitive, which is worse: an undated entry between two dated
# ones matches both and the answer depends on iteration order.
UNDATED = (
    SECTION + "**[Lane A → Lane G]** — **a date added after the first import.** **Status:** OPEN\n"
)
DATED = UNDATED.replace("Lane G]** —", "Lane G]** 2026-03-04 —")
undated_rows, _ = ledger.entries(UNDATED)
dated_rows, _ = ledger.entries(DATED)
check("the edit added a date", (undated_rows[0].date, dated_rows[0].date), (None, "2026-03-04"))
rekeyed = reconcile.reconcile(dated_rows, [record_of(undated_rows[0])])
check("adding a date re-keys, so the row duplicates", len(rekeyed.create), 1)
check(
    "and the old one is reported as orphaned rather than left unexplained", len(rekeyed.orphan), 1
)

print()
print("status, narrowed to two of the schema's three")

closed = entry_with(CENSUS, "ASCII `->` instead of U+2192")
check("a closed entry maps to closed", reconcile.status_of(closed), "closed")
check("an accepted one maps to open, deliberately", reconcile.status_of(dated), "open")
check(
    "and the parser says it is accepted, so the narrowing is a choice not an oversight",
    dated.status.startswith("ACCEPTED"),
    True,
)

print()
print("the schema accepts what this writes")

check(
    "a record carrying an imported key validates",
    validate.validate(record_of(dated), validate.load("handoff")),
    [],
)
check(
    "and so does one with no date",
    validate.validate(record_of(undated, "u"), validate.load("handoff")),
    [],
)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
