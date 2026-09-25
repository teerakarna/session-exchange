"""Reading the handoff half of a markdown ledger.

This is the read side of a one-way door. The format below was never specified: it accreted in a
hand-maintained file with no version control, no backup and no delimiter of its own, and everything
here was measured against a real one rather than designed. The point of parsing it is to stop having
to, so nothing in this module is a format to build on.

Read `plans/2026-09-25_portable-session-exchange/ledger-input-contract.md` before changing any
pattern here. Every constant has a measurement behind it and several look arbitrary until you have
the counts. The ones that bite:

**Two guards are needed to find the section, not one.** A prose subheading elsewhere in the file
quotes the section's own name in its title, so "the heading that contains the name" silently
resolves to the decoy and yields nothing. The heading must *start with* the name, and the section
must contain at least one entry. Known limit, not handled: a fenced code block holding an example
entry at column 0 satisfies the second guard, so a style section written that way would win. It is
left alone because the symptom is loud - the wrong section yields a visibly wrong count on a dry
run, and the counts are printed for exactly that reason - whereas handling it means tracking fences
through the whole file.

**The anchors are narrow on purpose.** Roughly twenty body lines open with `**` as bold prose, and a
deliberately wide candidate pattern matched 45 lines against 18 real entries. `**` alone is not an
anchor. Nor is "any arrow-like glyph": a different arrow marks the tail of an entry further up and
is not a handoff at all, so the arrows wanted are named individually.

**Closure is read only from positions that mean closed.** An unqualified keyword search closed a
real entry on the phrase "no harm done" in a trailing prose clause. The rule is a keyword in marker
spelling (caps), or a keyword next to a status label. The deliberate trade: a closure written in
lowercase prose with no label reads as open, which is visible and recoverable. The inverse is
neither.

**Accepting is not closing.** A lane taking ownership is not the work being finished, and an
accepted entry with no later closure is exactly the state that should stay visible.

**The original headline survives acknowledgement, and the current one does not.** The ledger's
convention is that a recipient edits the entry in place, pushing the original to the right of a
literal `Was:` marker. So the text changes while the identity does not, which is why nothing here
hashes an entry, and why `original_headline` is read from the whole block rather than the header
line: in one measured case it wrapped across two further lines.

This module parses. It does not key, dedupe or write anything.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Named individually rather than matched as a class, and that is the only thing excluding
# CONTINUATION: U+2193 marks the tail of an entry further up, so a pattern anchored on "arrow-like"
# counts it as a handoff and over-reports by one. Add it to the class below and nothing else stops
# it.
ARROW = "→"
ARROW_REVERSED = "←"
CONTINUATION = "↓"

# The header separator, written as an escape rather than a literal: U+2014 is indistinguishable from
# a hyphen at a glance in a diff, and here it is data being matched, not punctuation being used.
SEPARATOR = "\u2014"

# The documented convention's heading. Overridable because a heading is somebody's wording, not a
# property of the format, and this module should not be the reason a ledger has to be renamed.
DEFAULT_SECTION = "Open questions / handoffs"

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

# Shape A is the documented convention, bracketed and sender first. Shape B is undocumented, in
# current use, and the shape the previous parser missed entirely: recipient first, sender inline,
# no brackets. Both anchored at column 0, no list marker, no indentation.
ENTRY_A = re.compile(r"^\*\*\[")
ENTRY_B = re.compile(r"^\*\*\s*[" + ARROW + ARROW_REVERSED + r"]")

# The date, and a time suffix only so the fields after it start in the right place. A time occurs on
# some headers and its minutes are sometimes partly obfuscated, so `\d{2}:\d{2}` does not match it
# and `\d{1,2}:\S+` does. Nothing reads the time, so nothing parses it: the group exists to be
# consumed.
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b(?:\s+\d{1,2}:\S+)?")

# Three spellings of the status marker occur and all mean the same thing. Match the label, not one
# bold arrangement.
STATUS_LABEL = re.compile(r"Status\s*:", re.IGNORECASE)

# Five spellings were in use when this was measured, plus one added the same day. `accepted` is
# deliberately absent: see the module docstring.
CLOSED_WORDS = ("done", "closed", "resolved", "withdrawn", "superseded", "merged")

# Caps is itself the marker, so a keyword in caps counts without a label next to it. The two guards
# are what stop that being an unqualified search: a keyword is not a marker when it is part of an
# identifier or quoted as code. One entry's body discusses `CLOSED.search(header)` in backticks
# while the entry itself is open, and a bare `\b(CLOSED)\b` closes it - which is the same class of
# mistake as the "no harm done" one, just one layer further in.
CLOSED_MARKER = re.compile(
    r"(?<![\w.`])(" + "|".join(w.upper() for w in CLOSED_WORDS) + r")\b(?![.\w`])"
)
CLOSED_ANY_CASE = re.compile(r"\b(" + "|".join(CLOSED_WORDS) + r")\b", re.IGNORECASE)

# How far past a status label a keyword still counts as that label's value. Wide enough for the
# measured spellings, which put a date and sometimes a lane between the two, and narrow enough that
# an unrelated later sentence is not swept in.
STATUS_WINDOW = 80

# Where the status value stops, for display only. The closure test reads the whole window instead,
# so a status that truncates here is still read correctly: this only decides what gets shown.
STATUS_END = re.compile(r"\n|\*\*|\s\(|\.\s|,")

# The marker that preserves the original headline when a recipient acknowledges in place.
WAS = re.compile(r"Was\s*:", re.IGNORECASE)


class Entry(NamedTuple):
    """One handoff, as the file has it. No normalisation beyond whitespace in the text fields."""

    shape: str
    header: str
    block: str
    route: str | None
    sender: str | None
    recipients: list[str]
    date: str | None
    headline: str
    original_headline: str
    status: str | None
    closed: bool


def is_entry(line: str) -> bool:
    """Whether a line opens a handoff entry.

    The whole cost of getting this wrong is in the docstring above: too wide and twenty lines of
    bold prose become handoffs, too narrow and a shape in current use is invisible with no symptom
    other than a count nobody is checking.

    There is deliberately no separate rule excluding `CONTINUATION`. There was one, and it was dead:
    naming the two route arrows individually in `ENTRY_B` already excludes it, so deleting the extra
    guard changed no result in any test - a check that cannot fail. The exclusion now lives in the
    arrow class, which is why widening that class to "any arrow" is the thing not to do.
    """
    return bool(ENTRY_A.match(line) or ENTRY_B.match(line))


def normalise_label(label: str) -> str:
    """A label in a form two spellings of it compare equal in.

    The same label appears both spaced and unspaced around `/`, `&` and `+`, and both spellings are
    current, so neither side can be treated as the correct one. Case is folded for the same reason.
    """
    folded = re.sub(r"\s*([/&+])\s*", r"\1", label)
    return re.sub(r"\s+", " ", folded).strip().casefold()


def split_route(route: str) -> tuple[str | None, list[str]]:
    """`(sender, recipients)` from a route field.

    Three cases, all measured. An arrow splits sender from recipients. A reversed arrow means the
    same pair written the other way round, so the sides swap. And a single label with no arrow at
    all is a recipient, not a sender: the entry is addressed to it.
    """
    if ARROW in route:
        left, _, right = route.partition(ARROW)
    elif "->" in route:
        left, _, right = route.partition("->")
    elif ARROW_REVERSED in route:
        right, _, left = route.partition(ARROW_REVERSED)
    elif "<-" in route:
        right, _, left = route.partition("<-")
    else:
        return None, [part.strip() for part in route.split("+") if part.strip()]
    recipients = [part.strip() for part in right.split("+") if part.strip()]
    return left.strip() or None, recipients


def sections(text: str) -> list[tuple[str, str]]:
    """Every heading in the file as `(heading text, body)`.

    A body runs to the next heading at the same level or shallower, which is what makes a subheading
    inside a section part of that section rather than a sibling of it.
    """
    lines = text.split("\n")
    heads = []
    for index, line in enumerate(lines):
        found = HEADING.match(line)
        if found:
            heads.append((index, len(found.group(1)), found.group(2)))
    out = []
    for position, (index, level, title) in enumerate(heads):
        end = len(lines)
        for later_index, later_level, _ in heads[position + 1 :]:
            if later_level <= level:
                end = later_index
                break
        out.append((title, "\n".join(lines[index + 1 : end])))
    return out


def find_section(text: str, name: str = DEFAULT_SECTION) -> tuple[str | None, str | None]:
    """The handoff section's body, or `(None, why not)`.

    Both guards are load-bearing and neither is sufficient. `startswith` alone resolves to a prose
    subheading that quotes the section's name in its own title; "has entries" alone would accept any
    section that happens to contain an entry-shaped line. Requiring both is what makes the answer
    unambiguous without hardcoding which heading is the decoy.
    """
    wanted = normalise_label(name)
    named = [body for title, body in sections(text) if normalise_label(title).startswith(wanted)]
    if not named:
        return None, f"no heading starts with {name!r}"
    withentries = [body for body in named if any(is_entry(line) for line in body.split("\n"))]
    if not withentries:
        return None, f"{len(named)} heading(s) start with {name!r}, none containing an entry"
    return withentries[0], None


def _fields_a(paragraph: str) -> tuple[str | None, str | None, str]:
    """`(route, date, headline)` for shape A.

    The date is read as the first one after the route rather than by position, because a route may
    contain digits and the closure date is written after the entry's own. Read from the paragraph
    rather than the header line: a wrapped headline is the case most likely to break a line-anchored
    matcher, and it is also the case where the status marker lands on the second line.
    """
    bracket = SHAPE_A.match(paragraph)
    # Sliced from the end of the bracket rather than from the end of the route text, so the closing
    # bracket goes with it. Splitting on the route leaves the `]` behind, which the date then hides
    # on every dated entry and leaks into the headline on the undated ones.
    route = bracket.group(1).strip() if bracket else None
    rest = paragraph[bracket.end() :] if bracket else paragraph
    found = DATE.search(rest)
    if not found:
        return route, None, _headline_from(rest)
    return route, found.group(1), _headline_from(rest[found.end() :])


def _clean(text: str) -> str:
    """Whitespace normalised and the decoration stripped, with the characters that are data kept.

    Emphasis markers and the header separator carry no meaning once the fields are split out. The
    arrows, the emoji severity flags and the ellipsis are data and are left alone.

    Only a `**` pair is stripped. A lone `*` is left alone, which is the fix rather than an
    omission: stripping single stars mangles a headline quoting a regex in backticks, and `\\*\\*`
    is not a pair because the backslash sits between the stars. An escape-aware `(?<!\\\\)` version
    was written first and then removed, because no arrangement of the data could tell it apart from
    this one - an untestable branch guarding a case that cannot occur is worse than not having it.
    """
    stripped = text.replace("**", " ").replace(SEPARATOR, " ")
    return re.sub(r"\s+", " ", stripped).strip(" .:")


# Shape A's route, bounded by its brackets. The bracket is the whole reason this shape is easy and
# the other is not: an explicit terminator means a recipient containing free text, digits or an
# arrow costs nothing to read.
SHAPE_A = re.compile(r"^\*\*\[([^\]]*)\]")


def _partition_sender_clause(body: str) -> tuple[str, str, str]:
    """Split a shape B header on the clause that names the sender.

    Measured as `, from ` in every occurrence. Kept as its own function because it is the one part
    of shape B that is a guess about wording rather than a measurement of structure, so it is the
    first thing to widen if a header stops parsing.
    """
    found = re.search(r",\s*from\s+", body, re.IGNORECASE)
    if not found:
        return body, "", ""
    return body[: found.start()], found.group(0), body[found.end() :]


def _fields_b(paragraph: str) -> tuple[str | None, str | None, str]:
    """`(route, date, headline)` for shape B, with the route rewritten into shape A's order.

    The file writes recipient first here and sender first in shape A. Normalising the order at parse
    time is what lets one comparison work across both shapes, so nothing downstream has to know
    which shape a record came from.

    The sender clause runs to the date, which is the only reason this shape can be split at all.
    When there is no date it runs to the first sentence break instead, which is a guess: an undated
    shape B header has not been observed, and the alternative is dropping the record silently.
    """
    body = paragraph.lstrip("* ").strip()
    recipient_part, marker, tail = _partition_sender_clause(body)
    if not marker:
        return None, None, _headline_from(body)
    recipient = _clean(recipient_part).lstrip(ARROW + ARROW_REVERSED + " ")
    found = DATE.search(tail)
    if found:
        sender, rest, date = tail[: found.start()], tail[found.end() :], found.group(1)
    else:
        cut = re.search(r"\.(?:\s|\*|$)|\*\*", tail)
        end = cut.start() if cut else len(tail)
        sender, rest, date = tail[:end], tail[end:], None
    sender = _clean(sender)
    if not sender:
        return None, date, _headline_from(rest)
    return f"{sender} {ARROW} {recipient}", date, _headline_from(rest)


def _headline_from(text: str) -> str:
    """The headline with the status clause taken out of it.

    Usually the status marker follows the headline, so the headline is everything before it, and the
    `Was:` marker ends it for the same reason: what follows that is the previous headline, not this
    one. In one measured header the order is reversed and the marker sits mid-sentence, with the
    headline after the separator that closes the status value, which is why this is not a single
    split: taking the text before the label there yields an empty headline, and an empty headline is
    not a parse failure anything downstream would notice.
    """
    label = STATUS_LABEL.search(text)
    was = WAS.search(text)
    ends = [found.start() for found in (label, was) if found]
    if ends:
        before = _clean(text[: min(ends)])
        if before:
            return before
    if not label:
        return _clean(text)
    after = text[label.end() :]
    _, separator, tail = after.partition(SEPARATOR)
    return _clean(tail) if separator else _clean(after)


def _original_headline(block: str, headline: str) -> str:
    """The headline as it was before any acknowledgement.

    Read from the block rather than the header line, because the preserved original wraps in one of
    the measured cases. Bounded by the end of the bold run when there is one, and by the end of the
    paragraph otherwise, since `Was:` is inserted inside the headline's own emphasis.
    """
    found = WAS.search(block)
    if not found:
        return headline
    tail = block[found.end() :]
    end = tail.find("**")
    if end == -1:
        end = tail.find("\n\n")
    if end != -1:
        tail = tail[:end]
    return _clean(tail) or headline


def _status_and_closed(block: str) -> tuple[str | None, bool]:
    """`(status text, closed)` read only from positions that mean it.

    Two accepted positions, both measured, and the asymmetry between them is the whole point. A
    keyword in marker spelling counts anywhere, because caps is itself the marker. A lowercase
    keyword counts only next to a status label, because otherwise it is prose: "no harm done" closed
    a real entry for ten days.
    """
    statuses = []
    closed = False
    for found in STATUS_LABEL.finditer(block):
        value = block[found.end() : found.end() + STATUS_WINDOW]
        # The commonest spelling is `**Status:** OPEN`, where the `**` straight after the colon
        # closes the label rather than ending the value. Dropping it first is the difference between
        # reading a status and reading an empty string for every entry in the file. `.lstrip()`
        # after it, because a marker at the end of a line puts its value on the next one. Without it
        # the first newline ends the value and every wrapped status reads as empty, which is
        # invisible: closure still comes out right, because that is read from the whole window.
        shown = re.sub(r"^\s*\*\*", "", value).lstrip()
        stop = STATUS_END.search(shown)
        statuses.append(_clean(shown[: stop.start()] if stop else shown))
        if CLOSED_ANY_CASE.search(value):
            closed = True
    if CLOSED_MARKER.search(block):
        closed = True
    return (statuses[0] or None) if statuses else None, closed


def entries(text: str, name: str = DEFAULT_SECTION) -> tuple[list[Entry], str | None]:
    """Every handoff in the section, and a problem if there is one.

    A problem rather than an exception, and a count rather than silence, because the failure this
    replaces was a parser that found nothing and said nothing: a section with content and zero
    entries parsed is indistinguishable from a quiet week unless something says so out loud.
    """
    body, problem = find_section(text, name)
    if body is None:
        return [], problem
    lines = body.split("\n")
    starts = [index for index, line in enumerate(lines) if is_entry(line)]
    if not starts:
        return [], "the section has content but no entry parsed out of it"
    out = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        for index in range(start + 1, end):
            if lines[index].startswith("## "):
                end = index
                break
        block = "\n".join(lines[start:end]).strip("\n")
        out.append(_entry(lines[start], block))
    return out, None


def _paragraph(block: str) -> str:
    """The block up to its first blank line.

    The header and its wrapped continuation are one sentence and have to be read together, while the
    paragraphs after the blank line are body: prose there mentions dates, lanes and arrows that are
    not this entry's, so widening the field extraction to the whole block reads them as data.
    """
    out = []
    for line in block.split("\n"):
        if not line.strip():
            break
        out.append(line)
    return "\n".join(out)


def _entry(header: str, block: str) -> Entry:
    shape = "A" if ENTRY_A.match(header) else "B"
    paragraph = _paragraph(block)
    route, date, headline = _fields_a(paragraph) if shape == "A" else _fields_b(paragraph)
    sender, recipients = split_route(route) if route else (None, [])
    status, closed = _status_and_closed(block)
    return Entry(
        shape=shape,
        header=header,
        block=block,
        route=route,
        sender=sender,
        recipients=recipients,
        date=date,
        headline=headline,
        original_headline=_original_headline(block, headline),
        status=status,
        closed=closed,
    )
