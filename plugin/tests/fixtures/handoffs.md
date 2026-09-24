## Open questions / handoffs

**[Lane A → Lane B]** 2026-01-02 — **canonical shape, and the majority case: one physical line, U+2192
arrow with a space either side, U+2014 separator with a space either side, status marker at the end of
the same line.** **Status:** OPEN

Continuation paragraph. Starts at column 0, no list marker, no indentation, so indentation cannot be
used to detect it. The entry runs from its header line to the next blank line; the body runs on to the
next header or the next `## ` heading.

**[Lane C / D → Lane E/F]** 2026-01-03 14:2xZ — **three variations in one header: spaces around the
slash in the sender's label, none in the recipient's, and a time suffix on the date whose minutes are
partly obfuscated, so `\d{2}:\d{2}` will not match it.** **Status: ACCEPTED by Lane E/F 2026-01-04.**

**[Lane G -> Lane H]** 2026-01-05 — ASCII `->` instead of U+2192, and no bold on the headline at all.
**Status:** DONE 2026-01-06

**[Lane A → Lane B + Lane C / D + Lane G]** 2026-01-07 — **several recipients, joined with ` + `, mixing
both spellings of the same label style.** **Status:** OPEN

**[Lane B]** 2026-01-08 — ⚠️ **no route at all: a single label, no arrow, and an emoji immediately after
the separator.** **Status:** WITHDRAWN

**[Lane A → Lane B]** 2026-01-09 — **headline wrapped across two physical lines, which is the case most
likely to break a line-anchored matcher: the status marker is on the second line, not the header
line.** **Status: OPEN.**

**→ Lane H, from Lane A 2026-01-10.** **second shape, and the one a `^\*\*\[` anchor misses entirely:
recipient first, sender inline after `from`, date terminated by a full stop rather than a separator,
and no brackets anywhere.**

**Status:** DONE 2026-01-11 (status on its own line at column 0, immediately after the header, no blank
line between them).

**→ whoever holds the credential (Lane G), from Lane B 2026-01-12. Status: SUPERSEDED 2026-01-13 by
Lane A — second shape again, this time with a free-text recipient and a bare `Status:` inside the
prose instead of a bold marker of its own.**

**↓ tail of an earlier entry (TICKET-1234), Lane A 2026-01-14 —** its opening paragraphs were pruned;
this is a continuation marker for an entry further up, not a new handoff. A matcher that counts it as
one over-reports.

**This line must not match.** It opens with `**` and is bold, but it is body prose belonging to the
entry above it. An anchor of `^\*\*` rather than something stricter over-matches here, and there are
~20 lines of this shape in the file it is modelled on.

**[Lane A → Lane B]** 2026-01-15 — **prose closure trap: no harm done, and no status marker anywhere
in the entry.** Added 2026-09-25 from a real header found during the replay. The keyword has to sit
on the header LINE to exercise the header test at all - an earlier version of this entry put it on
the continuation line below, where `CLOSED.search(header)` never saw it, so the fixture agreed with
both the broken and the fixed parser and proved nothing. An unqualified case-insensitive search here
closes this entry, wrongly. It is an open ask.

**[Lane A → Lane B]** 2026-01-16 — a closure keyword in lowercase but sitting next to a status label,
Status: done 2026-01-17, which must still close so the widened marker test keeps working.
