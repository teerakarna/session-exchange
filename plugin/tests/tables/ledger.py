"""The rules `ledger.py` has to keep, one broken way each.

Every constant in that module has a measurement behind it, and most of these break one: a guard
that was added because a real ledger defeated the version without it. The failure mode they share
is the one the module exists to end, a parse that finds fewer entries, or the wrong ones, and says
nothing about it.
"""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="ledger",
        rule="the continuation arrow marks the tail of another entry and is not a handoff",
        old='ENTRY_B = re.compile(r"^\\*\\*\\s*[" + ARROW + ARROW_REVERSED + r"]")',
        new='ENTRY_B = re.compile(r"^\\*\\*\\s*[" + ARROW + ARROW_REVERSED + CONTINUATION + r"]")',
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="shape B is an entry too, which is the shape the old parser missed entirely",
        old="    return bool(ENTRY_A.match(line) or ENTRY_B.match(line))",
        new="    return bool(ENTRY_A.match(line))",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="labels compare case-folded, since both casings are current",
        old='    return re.sub(r"\\s+", " ", folded).strip().casefold()',
        new='    return re.sub(r"\\s+", " ", folded).strip()',
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="spacing around / & + is not part of a label",
        old='    folded = re.sub(r"\\s*([/&+])\\s*", r"\\1", label)',
        new="    folded = label",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="a reversed arrow is the same pair written the other way round, so the sides swap",
        old="        right, _, left = route.partition(ARROW_REVERSED)",
        new="        left, _, right = route.partition(ARROW_REVERSED)",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="a route with no arrow names the recipient, not the sender",
        old='        return None, [part.strip() for part in route.split("+") if part.strip()]',
        new="        return route.strip() or None, []",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="a section ends at the next heading at its own level, not only a shallower one",
        old="            if later_level <= level:",
        new="            if later_level < level:",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="the section heading has to start with the name, or a prose decoy quoting it wins",
        old="if normalise_label(title).startswith(wanted)]",
        new="if wanted in normalise_label(title)]",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="the section has to contain an entry, the second of the two guards",
        old=(
            "    withentries = [body for body in named "
            'if any(is_entry(line) for line in body.split("\\n"))]'
        ),
        new="    withentries = named",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="an entry block stops at the next second-level heading",
        old='            if lines[index].startswith("## "):',
        new="            if False:",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="a caps keyword inside an identifier or backticks is not a closure marker",
        old='    r"(?<![\\w.`])(" + "|".join(w.upper() for w in CLOSED_WORDS) + r")\\b(?![.\\w`])"',
        new='    r"(" + "|".join(w.upper() for w in CLOSED_WORDS) + r")\\b"',
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="a lowercase keyword closes only next to a status label, never in prose",
        old="        if CLOSED_ANY_CASE.search(value):",
        new="        if CLOSED_ANY_CASE.search(block):",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="the ** closing a status label is not the start of its value",
        old='        shown = re.sub(r"^\\s*\\*\\*", "", value).lstrip()',
        new="        shown = value.lstrip()",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="the original headline is read from behind the Was: marker",
        old="    return _clean(tail) or headline",
        new="    return headline",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="Was: ends the current headline, as the status label does",
        old="    ends = [found.start() for found in (label, was) if found]",
        new="    ends = [label.start()] if label else []",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="a status written before the headline leaves the headline after its separator",
        old="    return _clean(tail) if separator else _clean(after)",
        new="    return _clean(after)",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="shape A's closing bracket goes with the route, not into the headline",
        old="    rest = paragraph[bracket.end() :] if bracket else paragraph",
        new="    rest = paragraph[bracket.end() - 1 :] if bracket else paragraph",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="shape B is rewritten sender first, so one comparison works across both shapes",
        old='    return f"{sender} {ARROW} {recipient}", date, _headline_from(rest)',
        new='    return f"{recipient} {ARROW} {sender}", date, _headline_from(rest)',
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="fields come from the header paragraph only, never from the body after it",
        old="        if not line.strip():\n            break",
        new="        if not line.strip():\n            continue",
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="only a ** pair is decoration, a lone * is data",
        old='    stripped = text.replace("**", " ").replace(SEPARATOR, " ")',
        new='    stripped = text.replace("*", " ").replace(SEPARATOR, " ")',
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="a time with partly obfuscated minutes is still consumed after the date",
        old='DATE = re.compile(r"\\b(20\\d\\d-\\d\\d-\\d\\d)\\b(?:\\s+\\d{1,2}:\\S+)?")',
        new='DATE = re.compile(r"\\b(20\\d\\d-\\d\\d-\\d\\d)\\b(?:\\s+\\d{2}:\\d{2})?")',
        caught_by="test_ledger.py",
    ),
    Mutation(
        module="ledger",
        rule="the status label matches in any case",
        old='STATUS_LABEL = re.compile(r"Status\\s*:", re.IGNORECASE)',
        new='STATUS_LABEL = re.compile(r"Status\\s*:")',
        caught_by="test_ledger.py",
    ),
]
