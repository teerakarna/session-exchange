# A ledger, synthesised

Every line below is invented to model one shape each. Nothing is copied from any real ledger: the
shapes are the specification, the wording is not, and the lane names are letters for the same reason
the other fixtures' directories are named for their shape.

This file covers what `handoffs.md` does not: acknowledgement in place, a reversed arrow, an entry
with no date, and the two headings that make finding the section harder than a substring match.

## Open questions / handoffs - how to write one

A style note. This heading *starts with* the section name and holds no entry, which is the whole case
the second guard exists for: match on `startswith` alone and this section wins, silently, and the
importer reports nothing to import on a file that is full of handoffs.

An example, indented so it is not at column 0 and so not an entry:

    **[Lane A → Lane B]** 2026-02-01 — **headline.** **Status:** OPEN

A fenced example at column 0 would satisfy the second guard and this section would win. That is a
recorded limit rather than a handled case, for the reason in the module docstring.

### How the Open questions / handoffs section is read

This subheading quotes the section name in the middle of its title rather than at the start, so the
first guard rejects it. It is nested under the heading above, so its prose belongs to that section
and not to a section of its own.

## Open questions / handoffs

**[Lane A → Lane B]** 2026-02-01 — **acknowledged in place, so the headline on the page is the
recipient's rewrite and not what was sent. Was: the original headline, kept verbatim to the right of
the marker.** **Status:** ACCEPTED

**[Lane C → Lane D]** 2026-02-02 — **acknowledged in place and then closed by a bare caps marker with
no status label anywhere in the entry, which is the position the caps rule exists for. Was: the
original headline, which wraps across two further physical lines, so reading it from the header line
alone truncates it here and the truncation is invisible.** DONE 2026-02-03

**[Lane F ← Lane E]** 2026-02-04 — **reversed arrow: the recipient is written first and the arrow
points the other way, so the pair has to be swapped rather than read left to right.** **Status:**
RESOLVED

**[Lane A → Lane G]** — **undated: no date anywhere on the header, which is two of the historical
records, so the key has to degrade rather than fault.** **Status:** OPEN

**→ Lane H, from Lane B. Status: OPEN** — second shape with no date at all. This has not been observed
and the handling is a guess: with no date to end it, the sender clause ends at the first sentence
break instead. It is here to pin what the guess currently does.
