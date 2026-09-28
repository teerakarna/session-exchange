"""The rules `validate.py` has to keep, one broken way each."""

from .shape import Mutation

MUTATIONS = [
    Mutation(
        module="validate",
        rule="a keyword the validator does not implement raises rather than not applying",
        old="    unknown = set(schema) - IMPLEMENTED\n    if unknown:",
        new="    unknown = set(schema) - IMPLEMENTED\n    if False:",
        caught_by="test_validate.py",
    ),
    Mutation(
        module="validate",
        rule="true is not an integer, though Python thinks bool is a subclass of int",
        old='        if expected in ("integer", "number") and isinstance(instance, bool):',
        new="        if False:",
        caught_by="test_validate.py",
    ),
    Mutation(
        module="validate",
        rule="a trailing $ means what JSON Schema means by it",
        old=(
            '    if pattern.endswith("$") and not pattern.endswith("\\\\$"):\n'
            '        return pattern[:-1] + r"\\Z"'
        ),
        new='    if False:\n        return pattern[:-1] + r"\\Z"',
        caught_by="test_validate.py",
    ),
    Mutation(
        module="validate",
        rule="a pattern is a partial match, so anchoring stays the schema's job",
        old=(
            '        if "pattern" in schema and not re.search('
            '_end_anchored(schema["pattern"]), instance):'
        ),
        new=(
            '        if "pattern" in schema and not re.match('
            '_end_anchored(schema["pattern"]), instance):'
        ),
        caught_by="test_validate.py",
    ),
]
