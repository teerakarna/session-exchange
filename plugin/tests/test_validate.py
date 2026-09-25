#!/usr/bin/env python3
"""The validator, and the shipped schemas it has to cover.

The load-bearing check here is the last one: every keyword that appears anywhere in the schemas is
implemented in the validator. A hand-rolled partial validator is only safe with that property,
because without it the failure mode is a constraint that quietly does not get checked, and a
constraint that does not run looks exactly like a constraint that passed.

Everything else in here is a rule broken deliberately once, on the principle that a check which
cannot fail is not a check.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

import validate  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


CLAIM = {"session_id": "abc-123", "cwd": "/tmp/x", "updated_at": "2026-09-25T01:02:03Z"}
HANDOFF = {
    "id": "h1",
    "from": {"cwd": "/tmp/x"},
    "to": {"repo": "dotfiles"},
    "created": "2026-09-25T01:02:03Z",
    "status": "open",
    "body": "please look at the thing",
}
MARKER = {"name": "personal"}

print("the shipped schemas accept what the plugin writes")

for label, instance in (("exchange", MARKER), ("claim", CLAIM), ("handoff", HANDOFF)):
    check(f"a minimal valid {label}", validate.validate(instance, validate.load(label)), [])

check("a handoff addressed to a session rather than a scope",
      validate.validate(dict(HANDOFF, to={"session_id": "abc-123"}),
                        validate.load("handoff")), [])
check("an imported handoff needs no date",
      validate.validate(dict(HANDOFF, imported={"route": "a/b", "headline": "the thing"}),
                        validate.load("handoff")), [])

print("and reject what it must not")

handoff_schema = validate.load("handoff")
claim_schema = validate.load("claim")

# Exactly one addressing mode. Both at once is the mistake worth catching, because it reads as
# more specific and is actually ambiguous.
check("a handoff addressed both ways is refused",
      len(validate.validate(dict(HANDOFF, to={"repo": "x", "session_id": "abc"}),
                            handoff_schema)), 1)
check("a handoff addressed no way at all is refused",
      len(validate.validate(dict(HANDOFF, to={}), handoff_schema)), 1)
check("an unknown status is refused",
      len(validate.validate(dict(HANDOFF, status="done"), handoff_schema)), 1)
check("a session id that could climb out of its directory is refused",
      len(validate.validate(dict(CLAIM, session_id="../../etc/passwd"), claim_schema)), 1)
check("an unexpected key is refused",
      len(validate.validate(dict(CLAIM, lane="platform"), claim_schema)), 1)
# The location prefix is the caller's to supply, and `store` passes the filename so a problem read
# off disk says which file it came from. Both spellings are asserted, because a problem that cannot
# say where it is is not actionable.
check("a missing required key is named",
      validate.validate({"cwd": "/tmp/x"}, claim_schema),
      ["value: missing required key 'session_id'",
       "value: missing required key 'updated_at'"])
check("and carries the location the caller gave it",
      validate.validate({"cwd": "/tmp/x"}, claim_schema, "s1.json")[0],
      "s1.json: missing required key 'session_id'")
check("a loosely spelt timestamp is refused",
      len(validate.validate(dict(CLAIM, updated_at="2026-9-5 01:02"), claim_schema)), 1)

# `bool` is a subclass of `int` in Python, so an integer check written the obvious way accepts
# `true`. Asserted because it is the kind of thing that passes review and then lets a cap of `true`
# through into a renderer.
check("true is not an integer",
      len(validate.validate({"name": "x", "stale_days": True}, validate.load("exchange"))), 1)
check("but a real integer is",
      validate.validate({"name": "x", "stale_days": 14}, validate.load("exchange")), [])

print("an unimplemented keyword raises rather than silently not applying")

try:
    validate.validate("anything", {"type": "string", "maxLength": 3})
    check("a keyword the validator does not implement", "no exception", "UnsupportedSchema")
except validate.UnsupportedSchema as exc:
    check("a keyword the validator does not implement", "maxLength" in str(exc), True)

try:
    validate.validate("anything", {"type": "uuid"})
    check("a type the validator does not implement", "no exception", "UnsupportedSchema")
except validate.UnsupportedSchema:
    check("a type the validator does not implement", True, True)


def keywords(schema, seen):
    """Every keyword used anywhere in a schema.

    Mirrors the validator's own traversal on purpose. If the two ever disagree about where a schema
    node is, this check stops being meaningful, and that is a thing worth having to notice.
    """
    if not isinstance(schema, dict):
        return seen
    seen |= set(schema)
    for child in schema.get("properties", {}).values():
        keywords(child, seen)
    extra = schema.get("additionalProperties")
    if isinstance(extra, dict):
        keywords(extra, seen)
    if isinstance(schema.get("items"), dict):
        keywords(schema["items"], seen)
    for child in schema.get("oneOf", []):
        keywords(child, seen)
    return seen


used = set()
for name in ("exchange", "claim", "handoff"):
    keywords(validate.load(name), used)
check("every keyword the schemas use is implemented", sorted(used - validate.IMPLEMENTED), [])

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
