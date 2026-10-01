#!/usr/bin/env python3
"""The ledger parser, against the two synthesised fixtures.

`fixtures/handoffs.md` is the shape census the legacy hook was fixed against and its counts are the
ground truth this port must keep: 10 entries, 5 closed, with the continuation marker and the bold
prose line excluded. `fixtures/ledger-shapes.md` covers what that file does not model, which is
acknowledgement in place, a reversed arrow, an undated entry and the two headings that make finding
the section harder than a substring match.

Discipline, per CONTRIBUTING: a check has to be able to fail. Every gate here was broken
deliberately once and the failure recorded in the plan, and the negative case is asserted next to
the positive one wherever a rule is asserted at all. The two that matter most are both over-match
gates, because their failure mode is a number nobody checks rather than an error: the continuation
marker counted as a handoff, and a closure keyword read out of prose. Both are asserted on content
that is *there*, not by omission, so removing the rule fails the test rather than changing nothing.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import ledger

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
CENSUS = (FIXTURES / "handoffs.md").read_text()
SHAPES = (FIXTURES / "ledger-shapes.md").read_text()

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


# Returned when a lookup finds no single match, so the checks that follow report instead of raising.
# Two gates were verified by breaking them and both crashed with an AttributeError on None rather
# than naming the check that failed. An exit code is not a failure message.
MISSING = ledger.Entry(
    shape="",
    header="",
    block="",
    route=None,
    sender=None,
    recipients=[],
    date=None,
    headline="",
    original_headline="",
    status=None,
    closed=None,
)


def headline_of(rows, fragment):
    """The one entry whose headline contains `fragment`, so a check names a shape not an index.

    Indexes make a fixture fragile: inserting a shape renumbers every assertion after it, and the
    diff then hides which check actually changed meaning.
    """
    found = [r for r in rows if fragment in r.headline or fragment in r.original_headline]
    if len(found) != 1:
        print(f"  FAIL  lookup {fragment!r} matched {len(found)} entries, want 1")
        failures.append(f"lookup {fragment!r}")
        return MISSING
    return found[0]


census, census_problem = ledger.entries(CENSUS)
shapes, shapes_problem = ledger.entries(SHAPES)

print("the census fixture, whose counts are the legacy ground truth")

check("no problem reported", census_problem, None)
check("10 entries, not the 45 a wide pattern matches", len(census), 10)
check("5 of them closed", sum(1 for r in census if r.closed), 5)
check("both shapes are represented", sorted({r.shape for r in census}), ["A", "B"])

# The two over-match gates. Asserted on the text that must NOT produce an entry, so that deleting
# the rule fails here rather than passing quietly with a count of 12.
check(
    "the continuation marker is not a handoff",
    [r for r in census if "continuation marker for an entry" in r.headline],
    [],
)
check(
    "a bold prose line is not a handoff",
    [r for r in census if r.headline.startswith("This line must not match")],
    [],
)
check(
    "the marker line is body of the entry above it",
    any(ledger.CONTINUATION in r.block for r in census),
    True,
)

print()
print("closure, which is where an unqualified search costs the most")

trap = headline_of(census, "prose closure trap")
check("a keyword in lowercase prose with no label does not close", trap.closed, False)
check(
    "and that entry has no status at all, so the keyword was the only candidate", trap.status, None
)

lowercase = headline_of(census, "a closure keyword in lowercase but sitting next to a status label")
check("the same keyword next to a label does close", lowercase.closed, True)
check("and the label's value is read across the comma", lowercase.status, "done 2026-01-17")

accepted = headline_of(census, "three variations in one header")
check(
    "accepting is not closing",
    (accepted.status, accepted.closed),
    ("ACCEPTED by Lane E/F 2026-01-04", False),
)

caps = headline_of(shapes, "bare caps marker")
check("a caps keyword with no label anywhere still closes", caps.closed, True)
check("and it is the only signal, so status stays empty", caps.status, None)

# The caps rule's own over-match. This entry's body quotes `CLOSED.search(header)` in backticks
# while the entry is open, so a bare \b(CLOSED)\b closes it. Same class as "no harm done", one layer
# in.
check("a keyword quoted as code does not close", "CLOSED" in trap.block, True)
check("even though the token is there, verbatim, in the block", trap.closed, False)

print()
print("fields")

wrapped = headline_of(census, "headline wrapped across two physical lines")
check("a wrapped headline is read whole", wrapped.headline.endswith("not the header line"), True)
check("and its status, which sits on the second line, is found", wrapped.status, "OPEN")

ascii_arrow = headline_of(census, "ASCII `->` instead of U+2192")
check("an ASCII arrow routes", (ascii_arrow.sender, ascii_arrow.recipients), ("Lane G", ["Lane H"]))

many = headline_of(census, "several recipients")
check("recipients split on ` + `", many.recipients, ["Lane B", "Lane C / D", "Lane G"])

noroute = headline_of(census, "no route at all")
check(
    "a single label with no arrow is the recipient, not the sender",
    (noroute.sender, noroute.recipients),
    (None, ["Lane B"]),
)

obfuscated = accepted
check("a date parses with an obfuscated time after it", obfuscated.date, "2026-01-03")
check(
    "and the time does not leak into the headline",
    obfuscated.headline.startswith("three variations"),
    True,
)

shape_b = headline_of(census, "recipient first, sender inline")
check(
    "shape B is rewritten into shape A's order", shape_b.route, "Lane A " + ledger.ARROW + " Lane H"
)
check(
    "its status, which sits below the header with a blank line between, is found",
    shape_b.status,
    "DONE 2026-01-11",
)

freetext = headline_of(census, "free-text recipient")
check(
    "a free-text recipient survives whole",
    freetext.recipients,
    ["whoever holds the credential (Lane G)"],
)
check(
    "and a headline written after the status marker is still found",
    freetext.headline.startswith("second shape again"),
    True,
)

check("an emphasised regex in a headline is not mangled", "`^\\*\\*\\[`" in shape_b.headline, True)

print()
print("the shapes fixture: acknowledgement, reversed arrow, no date")

check("no problem reported", shapes_problem, None)
check("5 entries", len(shapes), 5)

acked = headline_of(shapes, "kept verbatim to the right of the marker")
check(
    "the original headline is recovered from the Was: marker",
    acked.original_headline,
    "the original headline, kept verbatim to the right of the marker",
)
check(
    "and the current headline stops at the marker",
    acked.headline.endswith("not what was sent"),
    True,
)
check(
    "so the two differ, which is the whole reason the key uses the original",
    acked.headline == acked.original_headline,
    False,
)

check(
    "a preserved original that wraps is read from the block, not the header line",
    caps.original_headline.endswith("the truncation is invisible"),
    True,
)

reversed_arrow = headline_of(shapes, "reversed arrow")
check(
    "a reversed arrow swaps the pair",
    (reversed_arrow.sender, reversed_arrow.recipients),
    ("Lane E", ["Lane F"]),
)
check(
    "and its status, written on the line below the label, is read",
    reversed_arrow.status,
    "RESOLVED",
)

undated = headline_of(shapes, "undated: no date anywhere")
check("an undated entry degrades rather than faults", undated.date, None)
check(
    "and the closing bracket does not leak into the headline",
    undated.headline.startswith("undated:"),
    True,
)

undated_b = headline_of(shapes, "second shape with no date")
check(
    "an undated shape B still routes",
    (undated_b.sender, undated_b.recipients, undated_b.date),
    ("Lane B", ["Lane H"], None),
)

print()
print("finding the section, where one guard is not enough")

body, problem = ledger.find_section(SHAPES)
check("the section is found despite two decoy headings", problem, None)
check("and it is the real one, not the style note", body.count("**["), 4)

# Guard 1 alone resolves to the style note, which starts with the name and holds no entry. Guard 2
# alone would accept any section containing an entry-shaped line. Both are asserted by removing the
# other's contribution rather than by trusting the combined result above.
style_note = [b for t, b in ledger.sections(SHAPES) if t.startswith("Open questions / handoffs -")]
check("the style note does start with the section name", len(style_note), 1)
check(
    "and holds no entry, which is the only thing separating them",
    any(ledger.is_entry(line) for line in style_note[0].split("\n")),
    False,
)
check(
    "its indented example is not an entry",
    ledger.is_entry("    **[Lane A " + ledger.ARROW + " Lane B]** 2026-02-01"),
    False,
)

mid_title = [
    t
    for t, _ in ledger.sections(SHAPES)
    if "Open questions / handoffs" in t and not t.startswith("Open questions")
]
check("a heading quoting the name mid-title exists", len(mid_title), 1)
check(
    "and is rejected, because startswith is not contains",
    ledger.find_section(
        "## How the Open questions / handoffs section is read\n\n**[A "
        + ledger.ARROW
        + " B]** 2026-01-01 - x\n"
    )[0],
    None,
)

print()
print("failing loudly, which is the whole point of the exercise")

check(
    "a missing section says so rather than returning nothing",
    ledger.entries("# nothing here\n")[1],
    "no heading starts with 'Open questions / handoffs'",
)
check(
    "a section with content but no entry says so too",
    ledger.entries("## Open questions / handoffs\n\nprose only, no entries at all.\n")[1],
    "1 heading(s) start with 'Open questions / handoffs', none containing an entry",
)
check("an empty file is not an exception", ledger.entries("")[0], [])
check(
    "a custom section name is honoured",
    len(
        ledger.entries(
            "## Handoffs\n\n**[A " + ledger.ARROW + " B]** 2026-01-01 - x\n", "Handoffs"
        )[0]
    ),
    1,
)

print()
print("the rules the mutation sweep found nothing asserting (#55)")

check("labels fold case", ledger.normalise_label("Ops"), "ops")
check("spacing around a separator is not part of a label", ledger.normalise_label("a / b"), "a/b")

nested, _ = ledger.entries(
    "# Open questions / handoffs\n\n**[A " + ledger.ARROW + " B]** 2026-01-01 - first\n\n"
    "## Notes\n\nprose under the next heading\n"
)
check(
    "an entry stops at a second-level heading inside its section",
    "prose under the next heading"
    in (nested[0].block if nested else "prose under the next heading"),
    False,
)

# The prose has to sit further from the label than `STATUS_WINDOW`, so that only a search of the
# whole block can reach it. Inside the window the keyword would count, and correctly.
far, _ = ledger.entries(
    "## Open questions / handoffs\n\n**[A " + ledger.ARROW + " B]** 2026-01-01 - headline "
    "**Status:** OPEN\n\n" + "filler " * 20 + "and the other lane got theirs done\n"
)
check(
    "a lowercase keyword in prose far from the label does not close",
    far[0].closed if far else None,
    False,
)
lower, _ = ledger.entries(
    "## Open questions / handoffs\n\n**[A " + ledger.ARROW + " B]** 2026-01-01 - headline "
    "status: done\n"
)
check(
    "a lowercase status label still counts as one",
    lower[0].closed if lower else None,
    True,
)


def one(header):
    """The single entry a one-line section parses to, or `None`."""
    found, _ = ledger.entries("## Open questions / handoffs\n\n" + header + "\n")
    return found[0] if found else None


check("the ASCII reversed arrow swaps the sides too", ledger.split_route("A <- B"), ("B", ["A"]))
merged = one("**[A " + ledger.ARROW + " B]** 2026-01-01 - headline **Status:** MERGED")
check("merged is a closure word", merged.closed if merged else None, True)
was = one("**[A " + ledger.ARROW + " B]** 2026-01-01 - new one was: old one here")
check(
    "a lowercase was: marker still holds the original",
    was and was.original_headline,
    "old one here",
)
sender_case = one("**" + ledger.ARROW + " B, From A 2026-01-01 - headline**")
check(
    "the sender clause matches in any case",
    sender_case and sender_case.route,
    "A " + ledger.ARROW + " B",
)
# Keyed as `>B` instead, an empty sender would pass for a route and reconcile would never report it.
no_sender = one("**" + ledger.ARROW + " B, from 2026-01-01 - headline**")
check("a shape B header with an empty sender has no route", no_sender and no_sender.route, None)
first, _ = ledger.find_section(
    "## Open questions / handoffs one\n\n**[A " + ledger.ARROW + " B]** 2026-01-01 - first\n\n"
    "## Open questions / handoffs two\n\n**[A " + ledger.ARROW + " B]** 2026-01-02 - second\n"
)
check("of two qualifying sections the first wins", "first" in (first or ""), True)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
