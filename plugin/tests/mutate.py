#!/usr/bin/env python3
"""Break one rule at a time and require the suite to notice.

This repo's one load-bearing rule is that a check has to be able to fail, and until now the tool
that enforces it lived in `/tmp`. It was written from scratch four times, pointed at one module
each time, and thrown away with the session, so neither its tables nor its own bug fixes survived.
That is what this file is for: the tables are the durable part, not the runner.

## How a sweep works

For each mutation: copy the repo to a scratch directory, replace one exact string in one module, run
the whole suite there, and require it to fail. A mutation the suite does not notice is a rule
nothing asserts, which reads as protection and is not, and is the defect class the project exists
to delete.

Before any of that, the unmutated copy has to pass. See `baseline` for why that is the load-bearing
line of the file rather than a nicety.

## The bug this harness already had

A mutation whose text no longer matched the file was scored as "no failure". So the tool built to
find checks that cannot fail had exactly that defect: it reported a real rule as untested while
hiding a fake one, and because it was rewritten by hand each time, the fix never persisted either.
Hence `assert_applied`: **if you mutate by string replacement, assert the replacement happened**,
and require exactly one occurrence so an edit that silently hits two places is a failure too.

## Why not coverage

Coverage said `hookio` was covered, and it is: `test_hook.py` executes every line of it through a
subprocess. Every one of those lines could be replaced with a constant and the suite stayed green.
Line coverage measures execution. What matters here is whether a wrong answer gets detected.

## Running it

    python3 plugin/tests/mutate.py            # every module with a table
    python3 plugin/tests/mutate.py hookio     # one module, while writing its table

Not named `test_*.py` on purpose, so `run.py` does not pick it up: one full suite run per mutation
is seconds rather than milliseconds. `test_mutations.py` is the fast half that does run there, and
it is what stops a table drifting away from the source it claims to patch.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import NamedTuple

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
LIB = PLUGIN / "lib"
# The whole repo, not just `plugin/`: `test_plugin_layout.py` reads the marketplace manifest at the
# repo root, so a scratch copy of `plugin/` alone fails that file on every run. See `baseline`.
REPO = PLUGIN.parent
IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".ruff_cache")


class Mutation(NamedTuple):
    """One rule, broken one way, and the test file that has to object.

    `caught_by` is pinned to a file rather than an individual check name: a file is stable enough to
    be worth asserting, while pinning the check name would turn every rename of a check into a red
    build. Membership only, so a mutation caught by its named file *and* two others still passes -
    which is the honest description, since nothing prints the extra names on a pass.
    """

    module: str
    rule: str
    old: str
    new: str
    caught_by: str


HOOKIO = [
    Mutation(
        module="hookio",
        rule="the event name is read from the payload, not from the wiring",
        old="    return name if isinstance(name, str) and name else default",
        new="    return default",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a payload with no event name falls back to the wiring",
        old="    return name if isinstance(name, str) and name else default",
        new="    return name",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a payload event name that is not a string falls back too",
        old="    return name if isinstance(name, str) and name else default",
        new="    return name if name else default",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="nothing to say means nothing printed, not an empty section",
        old="    lines = [line for line in lines if line]\n    if not lines:\n        return",
        new="    lines = [line for line in lines if line]\n    if False:\n        return",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a handler run by hand on a terminal returns instead of waiting forever",
        old="        if stream.isatty():\n            return {}",
        new="        if False:\n            return {}",
        caught_by="test_hook.py",
    ),
    # The three the first honest sweep found alive, in a module already recorded as swept. Each one
    # is a rule the module's docstring or a function's docstring states, with nothing behind it.
    Mutation(
        module="hookio",
        rule="a problem line is marked as coming from this plugin",
        old='    return f"[{PREFIX}] {text}"',
        new="    return text",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="lines are joined by a newline, not run together",
        old='"\\n".join(lines)',
        new='" ".join(lines)',
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="an empty line is dropped rather than injected as a gap",
        old="    lines = [line for line in lines if line]",
        new="    lines = list(lines)",
        caught_by="test_hook.py",
    ),
    # And the rest, found by review passes over this diff rather than by the first sweep, all in the
    # same module again. The first is the worst of every survivor: it breaks the guarantee the
    # project calls absolute.
    Mutation(
        module="hookio",
        rule="valid JSON that is not an object is no payload, not an exit 1 with a traceback",
        old="    return data if isinstance(data, dict) else {}",
        new="    return data",
        caught_by="test_hook.py",
    ),
    # And the half-fix this entry was first written against, worth its own mutation: `or {}` turns
    # the falsy non-objects into `{}` and passes `5`, `true` and `[1]` straight through, so a suite
    # that only ever feeds it `null` reads as cover for a guarantee still broken four ways.
    Mutation(
        module="hookio",
        rule="a truthy non-object is caught too, not just the falsy half",
        old="    return data if isinstance(data, dict) else {}",
        new="    return data or {}",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="the stream argument is the stream that gets read",
        old="    stream = sys.stdin if stream is None else stream",
        new="    stream = sys.stdin",
        caught_by="test_hook.py",
    ),
    # Named for what it breaks, which is the opposite of what its text said for two passes: this one
    # makes `emit` return unconditionally and inject nothing ever, while the entry above is the one
    # about an empty section. Two entries claiming the same rule reads as a duplicate and gets
    # deleted, taking the rule nothing else covers with it.
    Mutation(
        module="hookio",
        rule="having something to say means a reply is printed at all",
        old="    if not lines:\n        return",
        new="    return",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="a stream that cannot answer isatty is read rather than refused",
        old="    except (AttributeError, ValueError):\n        pass",
        new="    except ZeroDivisionError:\n        pass",
        caught_by="test_hook.py",
    ),
    # And the read below that guard, which named its exception types and was wrong about them three
    # passes running: `sys.stdin` is `None` when fd 0 is not open, a non-blocking stdin reads as
    # `None`, and a deeply nested array raises `RecursionError`. The mutation is the list coming
    # back, because the list is the defect rather than any one type missing from it.
    Mutation(
        module="hookio",
        rule="anything at all going wrong on the read is no payload, not a traceback out of main",
        old="    except Exception:\n        return {}",
        new="    except (ValueError, OSError):\n        return {}",
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="the reply is shaped the way Claude Code reads it, key included",
        old='            "hookSpecificOutput": {',
        new='            "hookSpecificOutputs": {',
        caught_by="test_hook.py",
    ),
    # The reader half of the guarantee, one mutation per state of it, because the first version of
    # this fix closed one of the three and the docstring claimed all three. A check fed back exactly
    # the input that showed the bug is the `or {}` shape again, one file over.
    #
    # The body removed rather than weakened. The two weaker versions - catching the `OSError` and
    # doing nothing, or flushing inside a wrapped `print` - both still exit 120, so either as a
    # `new` would be caught for a reason that has nothing to do with the rule.
    Mutation(
        module="hookio",
        rule="a stdout nobody is reading is silence, not an exit 120 on the way out",
        old="            null = os.open(os.devnull, os.O_WRONLY)\n"
        "            os.dup2(null, 1)\n"
        "            os.close(null)",
        new="            pass",
        caught_by="test_hook.py",
    ),
    # The write inside the same `try` as the flush. Expressed as the whole block swapped for the
    # version this was, with the `print` outside, because that is the shape of the defect: buffered,
    # the write succeeds and the flush is where the pipe breaks, so a fix that only guards the flush
    # passes every check written for the buffered case and raises on the unbuffered one.
    Mutation(
        module="hookio",
        rule="an unbuffered stdout breaks during the write, which is inside the guard too",
        old=(
            "    try:\n"
            "        print(reply, file=stream)\n"
            "        stream.flush()\n"
            "    except OSError:"
        ),
        new=(
            "    print(reply, file=stream)\n    try:\n        stream.flush()\n    except OSError:"
        ),
        caught_by="test_hook.py",
    ),
    Mutation(
        module="hookio",
        rule="no stdout at all is silence, not an AttributeError out of a hook",
        old="    if stream is None:\n        return",
        new="    if False:\n        return",
        caught_by="test_hook.py",
    ),
    # The narrowing guard on the redirect, which had thirteen lines of comment defending it and
    # nothing behind it: `if True` left the whole suite green, so the rule that `out=` is a seam and
    # not an fd was protection that was not.
    Mutation(
        module="hookio",
        rule="a stream the caller handed in is never fixed by redirecting fd 1",
        old="        if stream is sys.stdout:",
        new="        if True:",
        caught_by="test_hook.py",
    ),
]

STORE = [
    Mutation(
        module="store",
        rule="an id that cannot be a filename is refused rather than sanitised",
        old="    return value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None",
        new="    return value",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="fullmatch, because Python's $ also matches before a trailing newline",
        old="    return value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None",
        new="    return value if isinstance(value, str) and SAFE_ID.match(value) else None",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="an invalid object never reaches disk",
        old='            return f"refusing to write {path}: " + "; ".join(problems)',
        new="            pass",
        caught_by="test_store_claims.py",
    ),
    Mutation(
        module="store",
        rule="a file that exists and does not parse is never reported as absent",
        old=(
            "    except (OSError, ValueError) as exc:\n"
            '        return None, f"{path.name} could not be read: {exc}"'
        ),
        new="    except (OSError, ValueError):\n        return None, None",
        caught_by="test_store_claims.py",
    ),
]

VALIDATE = [
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

TABLES = {
    "hookio": HOOKIO,
    "store": STORE,
    "validate": VALIDATE,
}

# Modules with no table yet, listed rather than merely absent so that the debt is a thing you have
# to look at and a new module cannot join it by accident. `test_mutations.py` asserts this set plus
# the keys of TABLES is exactly what is in `plugin/lib`, so adding a module without deciding which
# half it belongs in fails the build. Tracked as issue #8.
#
# `ledger` and `reconcile` were swept in /tmp and passed; their tables were lost with the session
# and are not credited here, because a sweep nobody can re-run is a claim rather than a check.
UNSWEPT = {
    "claims",
    "cli",
    "exchange_root",
    "hook",
    "ledger",
    "legacy",
    "reconcile",
    "registry",
}


def apply(text, mutation):
    """The mutated source, or a reason it could not be produced.

    Exactly one occurrence required. Zero means the table has drifted from the source and the
    mutation is testing nothing; more than one means it is quietly breaking a second rule as well,
    so a pass would not say which one was caught.
    """
    found = text.count(mutation.old)
    if found != 1:
        return None, f"matched {found} times, need exactly 1"
    mutated = text.replace(mutation.old, mutation.new)
    # And the result has to still be Python. One step past the defect this file is proudest of
    # fixing: a mutation with a typo in it - a dropped colon, a mangled indent - stops the module
    # importing, every test file that touches it fails, the named one is among them, and the sweep
    # scores a catch. The rule was never exercised and the table now claims it is. Asserting the
    # replacement applied is not enough if what it applied is not a program.
    try:
        compile(mutated, f"<{mutation.module}.py mutated>", "exec")
    except SyntaxError as exc:
        return None, f"the result does not parse ({exc.msg} on line {exc.lineno})"
    return mutated, None


def prepare(scratch, mutation=None, mutated=None):
    """Lay out the copy of the repo the suite runs in, patched if there is a mutation.

    Split out of `run_suite` so the `unlink` is assertable, which it was not: deleting that line
    left the suite green, the sweep clean and all sixteen caught, while quietly making `verdict`'s
    "the suite passed, so nothing asserts this rule" branch unreachable for every mutation the sweep
    runs. That line is the third defect of that shape this file has had, and it had no check at all.
    """
    shutil.copytree(REPO, scratch, ignore=IGNORE)
    if mutated is None:
        return
    (scratch / "plugin" / "lib" / f"{mutation.module}.py").write_text(mutated, encoding="utf-8")
    # `test_mutations.py` asserts every table entry still matches its module, and a mutation is
    # exactly an edit that stops one matching, so in a mutated copy that file fails by construction
    # and says nothing about behaviour. Left in, it failed on all thirteen sweeps whatever the
    # mutation did, which made the survivor branch unreachable for exactly the mutations the sweep
    # runs and left `caught_by` doing that job by accident. Removed for the sweep only; the baseline
    # run keeps it, which is where it is meaningful.
    (scratch / "plugin" / "tests" / "test_mutations.py").unlink()


def run_suite(mutation=None):
    """Run the suite in a fresh copy of the repo, optionally with one module patched.

    Returns `(returncode, output)`, or `(None, reason)` if it could not be run at all. Output is
    stdout and stderr together: the scoring below reads a `FAILED:` line off stdout, and a suite
    that died rather than failed says why on stderr, which is the one case where the reason is the
    answer.
    """
    mutated = None
    if mutation is not None:
        source = LIB / f"{mutation.module}.py"
        mutated, problem = apply(source.read_text(encoding="utf-8"), mutation)
        if problem:
            return None, f"mutation did not apply: {problem}"

    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp) / "repo"
        prepare(scratch, mutation, mutated)
        try:
            done = subprocess.run(
                [sys.executable, str(scratch / "plugin" / "tests" / "run.py")],
                capture_output=True,
                text=True,
                # The suite is two seconds and the longest wait inside it is `test_hook.py`'s own
                # fifteen-second pty cap, so this is generous by two orders of magnitude and still
                # cheap: the point of a limit here is that the harness reports the hang itself
                # rather than the job dying at `timeout-minutes` with the summary unprinted, and
                # 600s against a 15 minute job means two hangs lose that report.
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return None, "the suite hung, which names nothing and blocks the sweep"
    return done.returncode, done.stdout + done.stderr


def baseline():
    """The unmutated copy has to pass, or nothing the sweep reports means anything.

    This is not defensive tidiness, it is the whole sweep. If the scratch copy fails for its own
    reason - a test reading a path the copy does not contain, say - then every run is non-zero, the
    "the suite passed, so nothing asserts this rule" branch below is unreachable, and every mutation
    is reported as caught no matter what it does. That happened on the first version of this file:
    the copy was `plugin/` alone, `test_plugin_layout.py` reads the marketplace manifest one level
    above it, and so a sweep that could not possibly find a survivor reported thirteen catches.

    The same shape as the bug the throwaway harness had, one level up: there, a mutation that did
    not apply was scored as a pass; here, a suite that could not pass was scored as a catch. Both
    are a gate that cannot fail, which is the thing this repo exists to stop shipping, and the
    harness has now produced it twice. Assert the ground you are standing on.
    """
    code, out = run_suite()
    return baseline_verdict(code, out)


def catchers(out):
    """The test files the runner named as failing, or None if it named none."""
    failed = re.search(r"^FAILED: (.+)$", out, re.MULTILINE)
    if not failed:
        return None
    return [name.strip() for name in failed.group(1).split(",")]


def last_line(out):
    """The last line of runner output, for the cases where no test file was named.

    A suite that died rather than failed prints a traceback and no `FAILED:` line, so the name the
    scoring normally reports does not exist and the reason on stderr is the only answer there is.
    Used by both scoring paths: `stderr` is captured precisely for this, and a branch that captures
    it and then reports a fixed string is the capture not being there.
    """
    lines = out.strip().splitlines()
    return lines[-1].strip() if lines else "no output at all"


def baseline_verdict(returncode, out):
    """The reason the baseline is unusable, or None. Split out so it can be asserted.

    See `verdict` for why the scoring does not live inside the function that shells out.
    """
    if returncode is None:
        return f"the unmutated suite could not be run: {out}"
    if returncode:
        named = catchers(out)
        which = ", ".join(named) if named else f"no test file named: {last_line(out)}"
        return f"the unmutated copy already fails ({which}), so no mutation result means anything"
    return None


def verdict(returncode, out, mutation):
    """Score one finished run: `(ok, detail)`. `ok` is False when the suite did not object.

    Separate from `run_suite` on purpose, and the reason is the history of this file. Every defect
    it has had was in the scoring, not in the running: a mutation that did not apply scored as a
    pass, a suite that could not pass scored as a catch, and a file failing by construction scored
    as the catcher. All three were invisible because scoring had no seam - it sat inside the
    function that shells out, so asserting it meant running sixteen real suites. Split apart,
    `test_mutations.py` feeds this synthetic runner output on the cheap job, and deleting the
    `caught_by` comparison stops being a silent change.
    """
    if returncode is None:
        return False, out
    if not returncode:
        return False, "the suite passed, so nothing asserts this rule"

    names = catchers(out)
    if not names:
        return False, f"the runner broke rather than failing: {last_line(out)}"
    if mutation.caught_by not in names:
        return False, f"caught by {', '.join(names)} rather than {mutation.caught_by}"
    return True, ", ".join(names)


def sweep_one(mutation):
    """Returns `(ok, detail)`. `ok` is False when the suite did not object."""
    returncode, out = run_suite(mutation)
    return verdict(returncode, out, mutation)


def main(argv):
    wanted = argv or sorted(TABLES)
    unknown = [name for name in wanted if name not in TABLES]
    if unknown:
        print(f"no table for: {', '.join(unknown)}")
        return 2

    print("=== baseline")
    problem = baseline()
    if problem:
        print(f"  STOP  {problem}")
        return 2
    print("  ok    the unmutated copy passes, so a failure below is the mutation's")

    survivors = []
    # Counted as the loop goes, not from `sum(len(TABLES[name]) for name in wanted)`, which is what
    # this did and which is a claim about the table rather than about work done. Both directions
    # were probed and both green: slicing the inner loop to `TABLES[name][:1]` ran 3 of 16 and still
    # printed "every one of 16 mutation(s) was caught", and dropping the argv filter from the outer
    # loop swept all 16 for `mutate.py hookio` and reported 8. Same reasoning as the `if not scored`
    # refusal below, one step out: a number nobody produced does not count either.
    scored = 0
    for name in wanted:
        print(f"=== {name}.py")
        for mutation in TABLES[name]:
            ok, detail = sweep_one(mutation)
            scored += 1
            print(f"  {'ok   ' if ok else 'ALIVE'} {mutation.rule}")
            # On a pass as well as on a survivor. `verdict` returns the files that objected and
            # nothing read the value, so it could have returned "" with the suite green - and it is
            # worth reading: a mutation caught by three files is a coupling nobody chose.
            print(f"        {detail}")
            if not ok:
                survivors.append((mutation, detail))

    print()
    if survivors:
        print(f"{len(survivors)} mutation(s) survived:")
        # The detail, not just the rule. `ALIVE` covers four different outcomes - nothing asserts
        # the rule, the table has drifted, the runner broke, the wrong file caught it - and only
        # the first is a finding. A summary naming the rule alone reports a stale `old` string as
        # "this rule is unasserted", a true-looking claim about the wrong thing, and the summary is
        # what gets read.
        for mutation, detail in survivors:
            print(f"  {mutation.module}: {mutation.rule}")
            print(f"    {detail}")
        return 1
    if not scored:
        # Otherwise this prints "every one of 0 mutation(s) was caught" and exits 0, which is a
        # green sweep that swept nothing. Reachable without anyone meaning it: move the tables into
        # `UNSWEPT` and the accounting in `test_mutations.py` still balances, so both gates stay
        # green forever. Same refusal as `baseline` - a result nothing produced does not count.
        print("no mutations to sweep, which proves nothing")
        return 1
    print(f"every one of {scored} mutation(s) was caught")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
