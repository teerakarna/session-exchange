"""Validate state against the schemas in `schemas/`, with no third-party dependency.

The plugin has to run wherever `python3` does and install nothing, so this covers the subset of
JSON Schema the shipped schemas actually use rather than the standard.

**An unrecognised keyword raises.** That is the one property which makes a hand-rolled partial
validator safe to rely on: the failure mode of a partial validator is a constraint that quietly
does not get checked, which looks exactly like a constraint that passed. Adding a keyword to a
schema therefore breaks the tests until it is implemented here, which is the correct direction for
that breakage to travel.
"""

from __future__ import annotations

import json
import pathlib
import re

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[1] / "schemas"

# Carry no constraint, so they need no implementation.
ANNOTATIONS = {"$schema", "$id", "title", "description", "default", "examples"}
IMPLEMENTED = ANNOTATIONS | {
    "type", "required", "properties", "additionalProperties", "items",
    "enum", "minimum", "minLength", "minItems", "pattern", "oneOf",
}

# `bool` is a subclass of `int` in Python, so an integer test has to exclude it explicitly or
# `true` validates as an integer.
TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


class UnsupportedSchema(Exception):
    """A schema uses a keyword this validator does not implement."""


def load(name):
    """Load a shipped schema by bare name, e.g. `claim`."""
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def validate(instance, schema, where="value"):
    """Problems as a list of strings. Empty means valid.

    Every problem names its own location, because "invalid claim" is not actionable and the whole
    point of validating at all is that a bad file says what is wrong with it.
    """
    unknown = set(schema) - IMPLEMENTED
    if unknown:
        raise UnsupportedSchema(
            f"{where}: schema uses unimplemented keyword(s) {sorted(unknown)}. "
            "Implement them in validate.py rather than letting them silently not apply."
        )

    problems = []

    if "oneOf" in schema:
        matched = [i for i, sub in enumerate(schema["oneOf"])
                   if not validate(instance, sub, where)]
        if len(matched) != 1:
            problems.append(
                f"{where}: must match exactly one of the {len(schema['oneOf'])} permitted shapes, "
                f"matched {len(matched)}"
            )
            return problems

    if "type" in schema:
        expected = schema["type"]
        if expected not in TYPES:
            raise UnsupportedSchema(f"{where}: unknown type {expected!r}")
        ok = isinstance(instance, TYPES[expected])
        if expected in ("integer", "number") and isinstance(instance, bool):
            ok = False
        if not ok:
            got = type(instance).__name__
            return problems + [f"{where}: expected {expected}, got {got}"]

    if "enum" in schema and instance not in schema["enum"]:
        problems.append(f"{where}: {instance!r} is not one of {schema['enum']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            problems.append(f"{where}: must be at least {schema['minLength']} character(s)")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            problems.append(f"{where}: {instance!r} does not match {schema['pattern']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            problems.append(f"{where}: must be at least {schema['minimum']}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                problems.append(f"{where}: missing required key {key!r}")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in properties:
                problems += validate(value, properties[key], f"{where}.{key}")
            elif extra is False:
                problems.append(f"{where}: unexpected key {key!r}")
            elif isinstance(extra, dict):
                problems += validate(value, extra, f"{where}.{key}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            problems.append(f"{where}: must have at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(instance):
                problems += validate(item, schema["items"], f"{where}[{i}]")

    return problems
