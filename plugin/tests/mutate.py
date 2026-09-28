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

    python3 plugin/tests/mutate.py                      # every module with a table
    python3 plugin/tests/mutate.py hookio               # one module, while writing its table
    python3 plugin/tests/mutate.py --since origin/main  # only what this change could have broken

The third form is what CI runs per push, and the cost is why: a sweep is one full suite run per
mutation, so its price is the mutation count times the length of the suite, and both halves grow.
Not linear in the size of the tables, which is what this said until #43 and what sized a job at
15 minutes against a sweep measured at 14m51s, which then hit the limit and was canceled at 15m15s
without finishing: a slow check added to a shared test file multiplies by every mutation in every
table, so a table written for one module makes the sweep of all the others dearer too. The run
prints the per-mutation figure at the end, so the estimate is measured rather than remembered - on
whichever machine ran it, and that is as fine as the figure goes. Two CI resweeps of the same 191
mutations, two commits apart, read 6.5s and 5.4s each, so the
runner's own spread is wider than any difference worth attributing to a change in the suite. The
limit in `ci.yml` is therefore sized off the slowest full resweep in the logs rather than the last.

Narrowing it to the modules a change can actually have affected keeps the per-push cost flat, and
the full sweep moves to a weekly schedule where the length of it does not matter. The narrowing only
started working when the tables moved out of this file (#36): a fix in this repo adds a mutation,
the tables lived here, and this file is in `INSTRUMENT`, so nearly every push paid the full sweep.
See `targets` for the derivation, which is wider than "the lib files that changed" for a reason.

Not named `test_*.py` on purpose, so `run.py` does not pick it up: one full suite run per mutation
is seconds rather than milliseconds. `test_mutations.py` is the fast half that does run there, and
it is what stops a table drifting away from the source it claims to patch.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

# The tables are a sibling package rather than part of this file, so that a diff adding a mutation
# narrows to the module it names instead of resweeping all nine - see `tables` for the derivation,
# and `INSTRUMENT` below for the half that stays wide. Bound as module globals rather than read
# through `tables.`, because `test_mutations.py` swaps all three for fixtures: the debt lists are
# meant to empty out, so a check keyed on a real member stops being able to fail the day the last
# table is written.
#
# `Mutation` is re-exported and not used here. The tables get it from `tables.shape`; a caller that
# builds one to feed this harness gets the harness and the shape it operates on from one import.
from tables import DECLINED, NOT_YET, TABLES, UNSWEPT, Mutation  # noqa: F401

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
LIB = PLUGIN / "lib"
# The whole repo, not just `plugin/`: `test_plugin_layout.py` reads the marketplace manifest at the
# repo root, so a scratch copy of `plugin/` alone fails that file on every run. See `baseline`.
REPO = PLUGIN.parent
IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".ruff_cache")

# Set in the environment of the suite a sweep spawns, and refused by `main` when it is set.
#
# Without it, 204 orphaned processes accumulated on one machine: a sweep prepares a copy, the suite
# runs inside that copy, and nothing stopped something in there starting another real sweep, which
# prepared another copy, and so on. Half a core for over two hours, and `ps` was the only trace it
# left - the temp directories go on the way out, and a sweep that dies mid-run orphans its children
# silently rather than reporting anything. Unbounded process growth is exactly a failure that does
# not report itself, which is what this repo is about.
#
# A flag rather than a depth counter. Depth would let one level of nesting through, and there is no
# reason to want one: the only honest answer to "start a sweep from inside a sweep" is no.
SWEEPING = "CC_EXCHANGE_SWEEPING"

# The files that decide what a sweep measures rather than being measured by it. `run.py` is what
# "the suite" means, this file is how a mutation is applied and scored, `tables/shape.py` is what a
# table entry is, and `tables/__init__.py` is which tables exist. A change to any of them makes the
# last sweep's verdicts stale for every module at once, so `--since` resweeps the lot.
#
# `tables/<module>.py` is deliberately not in here, and that is the whole of #36. The tables used to
# live in this file, so the set below matched nearly every PR in the repo - the rule here is that a
# fix adds a mutation, and a mutation was an edit to `mutate.py`. The narrowing applied only to a PR
# that changed behaviour and asserted nothing new about it, which is the PR this repo tries not to
# produce. Split per module, a new mutation is a diff in one path that names its own module.
INSTRUMENT = {
    "plugin/tests/run.py",
    "plugin/tests/mutate.py",
    "plugin/tests/tables/__init__.py",
    "plugin/tests/tables/shape.py",
}

# Test files that hold rules up across the whole of `plugin/lib` while being no mutation's
# `caught_by`, so the `caught_by` map cannot reach them. That is #27, and `test_cli.py` is the only
# instance: the sweep prints it alongside the named file for several `registry` and `legacy`
# mutations, because driving a command end to end exercises most of the lib whatever the command is.
#
# Left as a note rather than fixed for as long as the fix cost a full sweep on a common PR, which is
# most of the repo's history. #36 is what changes the arithmetic: with the tables split out, the
# full sweep is rare, so paying it for a change to the one file that could weaken any table is
# cheap. The alternative was recording per module which files the sweep saw objecting, and that is a
# second copy of what the sweep already prints, kept by hand, rotting the way the `old` strings rot.
BROAD = {"plugin/tests/test_cli.py"}

# Test files a sweep structurally cannot measure, as against merely does not. `prepare` deletes
# `test_mutations.py` from every mutated copy - it asserts that a table matches its module, and a
# mutation is exactly an edit that stops one matching, so it would fail by construction on every
# entry - which means no mutation can ever name it in `caught_by`.
#
# Its own set because the `caught_by` branch would otherwise print "named by no mutation, so no
# table maps this change" about it, which is true and useless: it reads as a table nobody has got
# round to, and the only thing anyone could do about it is the one thing the harness forbids. It
# still prints alongside "every table is reswept" on a harness PR, which the pair the `continue`
# above the loop removes was not: "reswept" and "no table maps this" contradict each other, while
# "reswept" and "this one path cannot be swept by anything" are both true and neither is the other's
# answer. The line stays because it is the only thing that explains a path selecting no module.
#
# The set is also what `prepare` deletes and what `test_mutations.py` holds `caught_by` against. A
# mutation naming a file in here would pass every check about the table - the file exists - and then
# be scored a permanent survivor, because the copy the suite runs in does not have the file that was
# supposed to object. Which is a red sweep on a rule that is asserted, the opposite defect to the
# one the sweep is for, and the check for it was missing until review asked what enforced this.
UNSWEEPABLE = {"plugin/tests/test_mutations.py"}


def targets(paths):
    """Which modules a change to `paths` makes worth sweeping, and what was left out.

    Returns `(modules, notes)`. Pure, and separate from the git call that feeds it, so the mapping
    is checkable without a repository or a commit - the derivation is the part that can be wrong
    in a way nothing notices, since its failure is a sweep that runs, passes, and measured the
    wrong thing.

    Four ways a path reaches a module:

    - `plugin/lib/<name>.py` is the module itself, the obvious half.
    - `plugin/tests/tables/<name>.py` is that module's table. The path is the mapping, which is why
      the tables are one file each rather than one file with nine lists in it: a pure function given
      a path can say which table a diff touched only if the path says so.
    - a test file maps through `caught_by`, because what the sweep asserts is that *the suite*
      objects, and a check deleted from that file is precisely how a mutation stops being caught. A
      sweep narrowed to changed lib modules alone would miss the whole of that, which is the failure
      this repo would have shipped: the file that weakens the gate is not the file the gate is
      about.
    - `INSTRUMENT` or `BROAD` is every table, for the two different reasons recorded on each.

    A note rather than a refusal for a changed module with no table. Failing would gate `cli`,
    `ledger` and `reconcile` behind writing tables for them, and a gate that blocks ordinary work
    gets bypassed, which is worse than the hole it was closing. The note says the change went
    unswept, and the weekly full sweep does not cover it either: `UNSWEPT` means unswept
    everywhere.

    The notes are printed on a wide run too, rather than returned only when the narrowing applies.
    They used to be skipped: `INSTRUMENT` returned early, so a PR that touched the harness and also
    changed `cli` swept everything and never said `cli` went unswept. Nothing was wrong with the
    module list, which is what a check on that path would have compared, and the line a reader
    needed was the one that went missing.

    A changed test file that no `caught_by` names gets a note for the same reason, which it did not
    for the first three tables (#24). Both halves were defensible alone - a file the tables do not
    reference genuinely cannot be swept, and the unswept notes were about lib modules - and together
    they printed "nothing that a sweep can measure changed" over a diff that added a test file and
    239 lines of checks. True, and not what a reader takes from it. `test_handlers.py` is the
    permanent case: the handlers are shell, which is outside anything this file can patch.

    The note for a test file says "no table maps this change" rather than "nothing measures it",
    because those are not the same: a file can catch mutations without being any mutation's
    `caught_by`, that field recording the one file that has to object rather than every file that
    does. `test_handlers.py` is the honest instance, the handlers being shell, and `test_cli.py` was
    the dishonest one until `BROAD`.

    `UNSWEEPABLE` gets its own wording for the third case, a file the sweep deletes from every copy
    it makes. "No table maps this change" is true of it and reads as a table nobody has written yet,
    when the harness forbids the only thing that would fix it. It also paired with "every table is
    reswept" on every harness PR, which is the contradiction the `continue` above is for.
    """
    paths = set(paths)
    # Wide for two different reasons, and both are said out loud rather than collapsed into one
    # line. "The instrument changed" and "a file that catches across every module changed" lead to
    # the same module list and to different follow-up actions, and the log is where it gets read.
    wide = []
    if INSTRUMENT & paths:
        wide.append("the sweep's own instrument changed, so every table is reswept")
    if BROAD & paths:
        named = ", ".join(sorted(path.rpartition("/")[2] for path in BROAD & paths))
        wide.append(
            f"{named} catches mutations across every module, so every table is reswept (#27)"
        )

    by_test = {}
    for name, table in TABLES.items():
        for mutation in table:
            by_test.setdefault(mutation.caught_by, set()).add(name)
    modules = set()
    notes = []
    for path in sorted(paths):
        # Handled above, and skipped here so the loop does not also report them as unmapped. Both
        # would otherwise fall through to the test-file branch, where no mutation names them: a
        # harness change would print "every table is reswept" and "mutate.py is named by no
        # mutation", which contradict each other and are both true.
        if path in INSTRUMENT or path in BROAD:
            continue
        parts = pathlib.PurePosixPath(path).parts
        if parts[0] != "plugin" or not path.endswith(".py"):
            continue
        name = pathlib.PurePosixPath(path).stem
        if len(parts) == 4 and parts[1:3] == ("tests", "tables"):
            # A table for a module the accounting knows. A file here that is not one is dead code -
            # nothing imports it, so no sweep reads it - and it gets a note rather than being
            # ignored, because a mutation written into a file nothing assembles is a rule somebody
            # believes is asserted.
            if name in TABLES:
                modules.add(name)
            else:
                notes.append(f"{path} is no module's table, so nothing assembles or sweeps it")
        elif len(parts) != 3:
            continue
        elif parts[1] == "lib":
            if name in TABLES:
                modules.add(name)
            elif name in DECLINED:
                notes.append(f"{name} changed and is deliberately not swept: {DECLINED[name]}")
            elif name in NOT_YET:
                notes.append(
                    f"{name} changed and has no table yet, so this change goes unswept (#55)"
                )
        elif parts[1] == "tests":
            named = by_test.get(parts[2], set())
            modules |= named
            if named:
                continue
            if path in UNSWEEPABLE:
                notes.append(
                    f"{parts[2]} is deleted from every mutated copy, so no mutation can name it"
                )
            else:
                notes.append(f"{parts[2]} is named by no mutation, so no table maps this change")
    if wide:
        return sorted(TABLES), wide + notes
    return sorted(modules), notes


def git(*args):
    """One git call in this repo, as a completed process. Never raises; the caller reads the status.

    Module level and passed in below rather than closed over, so the two failure paths in
    `changed_since` are reachable from a check. Without the seam the diff guard was unreachable by
    any input: a base git cannot resolve fails at `merge-base` first, so nothing could exercise the
    second guard, and deleting it left the suite green. A guard no input can reach is one this repo
    deletes - unless the reason it cannot be reached is the absence of a seam, which is a different
    problem with a different fix.
    """
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )


def changed_since(base, run=git):
    """Repo-relative paths that differ from `base`, or a reason there is no answer.

    The working tree rather than `HEAD`, so uncommitted edits count. Locally that is the common case
    and the one worth making cheap; in CI the tree is clean, so the two are the same thing.

    A merge base rather than `base` itself, or a branch that is behind main reports every file
    somebody else changed as its own. Untracked files are not consulted: a new module with no table
    fails the accounting in `test_mutations.py`, so the baseline stops the sweep before this
    matters.

    Any git failure is a reason, never an empty list. An empty list here means "nothing to sweep",
    which exits 0, so a git call that silently failed would be a green gate that swept nothing -
    the exact shape this file exists to delete.
    """
    found = run("merge-base", base, "HEAD")
    if found.returncode != 0:
        said = found.stderr.strip() or "git said nothing"
        return None, f"no merge base for {base!r} and HEAD: {said}"
    diff = run("diff", "--name-only", found.stdout.strip())
    if diff.returncode != 0:
        said = diff.stderr.strip() or "git said nothing"
        return None, f"cannot diff against {base!r}: {said}"
    return [line for line in diff.stdout.splitlines() if line], None


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
    #
    # Read off `UNSWEEPABLE` rather than naming the path again. The set and this line are one fact,
    # and written twice they drift in both directions: a second entry in the set and `targets` says
    # a file is deleted from every copy while the copy still has it, a deletion here and the note is
    # wrong the other way round.
    for path in sorted(UNSWEEPABLE):
        (scratch / path).unlink()


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
                # The marker travels with the child, so anything the suite starts inherits it and
                # `main` refuses. Copied from `os.environ` rather than passed alone, because the
                # suite needs PATH and the interpreter's own variables to run at all.
                env={**os.environ, SWEEPING: "1"},
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


def sections(out):
    """Runner output split by the `=== <file>` headers `run.py` prints, as `{file: text}`.

    So that "the named file objected" can be told from "the named file failed a check", which are
    not the same thing and scored the same until #42. `run.py` reports any non-zero child in its
    `FAILED:` line, and a test file that dies on a traceback exits non-zero, so the summary line the
    scoring reads cannot distinguish a rule that was asserted and failed from a file that stopped
    part way through and asserted nothing after that point.

    The one file whose own output contains `=== ` lines is `test_mutations.py`, whose synthetic
    runner fixtures print them, and `prepare` removes that file from every mutated copy - which is
    the only place this is read. Recorded rather than guarded against: a guard for it would be
    unreachable, and this file deletes those, but the coupling is worth knowing if that ever
    changes.

    `setdefault` on both branches, which is redundant on the second and deliberate. Written as a
    plain `found[current].append(line)`, dropping the `current is not None` guard raises KeyError,
    and a raise is the one report this repo will not take: it kills the check that exists to catch
    the defect and every check after it, which is #42 one level up. Written this way the same edit
    returns a `None` bucket holding the preamble, which is a wrong answer, and a wrong answer is
    what a check can object to.

    Which makes it the one line here no check can turn red on its own, and that is the trade rather
    than an oversight: reverting it changes nothing for any input, and it changes what a *different*
    deletion does. It costs something too. With a plain append, dropping the header branch's
    `setdefault` raised KeyError on the first body line of the first file, so every caller noticed;
    now it only changes the announced-and-silent case, and the whole of that rests on one check. A
    check going red beats a traceback at an arbitrary caller, which is this file's own subject, so
    both breaks landing on checks is the shape to want - but only while both checks exist."""
    found, current = {}, None
    for line in out.splitlines():
        header = re.match(r"^=== (\S+)$", line)
        if header:
            current = header.group(1)
            found.setdefault(current, [])
        elif current is not None:
            found.setdefault(current, []).append(line)
    return {name: "\n".join(body) for name, body in found.items()}


# `FAIL` followed by whitespace, which is the shape every check helper in this repo prints and is
# deliberately not `FAILED:`, the runner's own summary line. That line lands inside the last file's
# section, so matching it would report whichever file the glob happened to sort last as having
# failed a check, which is two inputs that agree in the one place that is asking which was read.
CHECK_FAILED = re.compile(r"^\s*FAIL\s")


def failed_a_check(out, name):
    """Whether the named file printed a failing check, rather than only exiting non-zero.

    Catches "died with no failing check at all", which is narrower than "died". A file that fails
    one check and then raises on the next line satisfies this and is scored an ordinary catch, so
    the rules it asserts after the crash point are still credited - the #41 shape, one check in.
    Telling that apart needs the count of checks the file was expected to print, and nothing has it:
    the runner prints per-file `ok`/`FAIL` lines but no total, and a mutated module legitimately
    changes how many checks run. The subset this does catch is the one that credited a whole file's
    worth of rules to a traceback; the rest is #57.
    """
    return any(CHECK_FAILED.match(line) for line in sections(out).get(name, "").splitlines())


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
    """Returns `(ok, detail, crashed)`. `ok` is False when the suite did not object.

    `crashed` is a caught mutation whose named file exited non-zero without a single check failing,
    which means it died part way through - and everything it would have asserted after that point
    went unasserted, for this mutation and for every other one that trips the same crash. It is not
    a survivor: a module mutated into raising is a legitimate way to be caught, and the sweep says
    so rather than failing. It is also not the same signal as a catch, which is #42. Found by
    breaking the overwrite refusal in #41 by hand, where a check asserted a substring against a
    value that is `None` exactly when the rule it covers is broken: the file died at check 14 of 34,
    the remaining twenty never ran, and the sweep reported full coverage of the table throughout.

    Computed here rather than inside `verdict` because it needs the output and the mutation
    together, and `verdict` is fed synthetic output by the cheap gate on the strength of being
    exactly the scoring and nothing else. `run_suite` is the seam this side is asserted through.
    """
    returncode, out = run_suite(mutation)
    ok, detail = verdict(returncode, out, mutation)
    if ok and not failed_a_check(out, mutation.caught_by):
        return True, f"{detail}, but no check in it failed, so it died rather than objecting", True
    return ok, detail, False


def main(argv):
    # Before the tables, before `baseline`, before anything that costs a suite run. A sweep reached
    # from inside a sweep is not a slow sweep but an unbounded one: each level prepares a copy and
    # runs a suite that can reach this line again. Exit 2 rather than 1, matching the other refusals
    # here - neither a clean sweep nor a survivor, but a run that should not have started.
    #
    # Blank and whitespace mean unset, matching what `exchange_root.resolve` does with the only
    # other CC_EXCHANGE_* variable rather than inventing a second convention one file over. Any
    # other value means set, `0` included: the question is whether a sweep is above this one, and
    # the refusal says which variable to unset if the answer is somehow no.
    if (os.environ.get(SWEEPING) or "").strip():
        print(f"refusing to sweep: {SWEEPING} is set, so this is already running inside a sweep")
        return 2

    argv = list(argv)
    since = None
    if argv and argv[0] == "--since":
        if len(argv) < 2 or not argv[1].strip():
            print("--since needs a ref to compare against")
            return 2
        since = argv[1]
        argv = argv[2:]
        # Refused rather than resolved in either direction. `--since main hookio` reads as both
        # "sweep hookio if it changed" and "sweep hookio, and also whatever else did", and the two
        # differ on exactly the runs where it matters. An ambiguous argument that quietly picks one
        # is how a sweep comes to measure something other than what the caller asked for.
        if argv:
            named = ", ".join(argv)
            print(f"--since derives the module list, so naming {named} as well is ambiguous")
            return 2

    if since is None:
        wanted = argv or sorted(TABLES)
        unknown = [name for name in wanted if name not in TABLES]
        if unknown:
            print(f"no table for: {', '.join(unknown)}")
            return 2
    else:
        paths, problem = changed_since(since)
        if problem:
            print(f"refusing to sweep: {problem}")
            return 2
        wanted, notes = targets(paths)
        print(f"=== {len(paths)} file(s) changed since {since}")
        for note in notes:
            print(f"  note  {note}")
        # Exit 0, and distinct from the "no mutations to sweep" refusal at the bottom of this
        # function. That one is a sweep asked to prove something and proving nothing; this one is a
        # change the sweep has nothing to say about - a doc, a workflow, a handler - and the honest
        # answer is to say so and not spend a suite run per mutation finding out again. The count
        # and the ref are printed either way, because "nothing changed" and "the ref was wrong"
        # look the same from here and only the log can tell them apart.
        if not wanted:
            print("nothing that a sweep can measure changed, so there is nothing to sweep")
            return 0
        print(f"  sweeping {', '.join(wanted)}")

    print("=== baseline")
    problem = baseline()
    if problem:
        print(f"  STOP  {problem}")
        return 2
    print("  ok    the unmutated copy passes, so a failure below is the mutation's")

    survivors = []
    crashes = []
    # Counted as the loop goes, not from `sum(len(TABLES[name]) for name in wanted)`, which is what
    # this did and which is a claim about the table rather than about work done. Both directions
    # were probed and both green: slicing the inner loop to `TABLES[name][:1]` ran 3 of 16 and still
    # printed "every one of 16 mutation(s) was caught", and dropping the argv filter from the outer
    # loop swept all 16 for `mutate.py hookio` and reported 8. Same reasoning as the `if not scored`
    # refusal below, one step out: a number nobody produced does not count either.
    scored = 0
    started = time.monotonic()
    for name in wanted:
        print(f"=== {name}.py")
        for mutation in TABLES[name]:
            ok, detail, crashed = sweep_one(mutation)
            scored += 1
            print(f"  {'crash' if crashed else 'ok   ' if ok else 'ALIVE'} {mutation.rule}")
            # On a pass as well as on a survivor. `verdict` returns the files that objected and
            # nothing read the value, so it could have returned "" with the suite green - and it is
            # worth reading: a mutation caught by three files is a coupling nobody chose.
            print(f"        {detail}")
            if not ok:
                survivors.append((mutation, detail))
            elif crashed:
                crashes.append((mutation, detail))

    print()
    # The unit cost, which is the figure the job's timeout is actually sized against and which two
    # files had wrong (#43). The sweep's price was described as linear in the size of the tables; it
    # is mutations times suite length, so a slow check added to a shared test file multiplies by the
    # whole mutation count and makes every older table's mutations slower too. Printed rather than
    # recomputed by hand from a comment, because the estimate is what broke a merge: #41 was
    # canceled at 15m15s against a 15-minute limit with a passing sweep.
    elapsed = time.monotonic() - started
    if scored:
        print(f"  cost  {scored} mutation(s) in {elapsed:.0f}s, {elapsed / scored:.1f}s each")
    # Ahead of the survivors, because a crash is a reason to distrust every verdict printed above it
    # and not just its own. A file that dies part way through asserts nothing after that point, for
    # this mutation and for every other one that trips the same crash, and the sweep reports the
    # rest of the table as covered throughout. Not an exit code: a module mutated into raising is a
    # legitimate way to be caught, and a gate that fails on a legitimate catch gets bypassed.
    if crashes:
        print(f"{len(crashes)} mutation(s) were caught by a file dying rather than by a check:")
        for mutation, detail in crashes:
            print(f"  {mutation.module}: {mutation.rule}")
            print(f"    {detail}")
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
