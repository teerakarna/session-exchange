#!/usr/bin/env python3
"""The mutation tables, checked without running a single sweep.

A sweep costs one full suite run per mutation, so it is its own CI job. This is the half that runs
in the ordinary suite, and it exists because the two ways a mutation table rots are both silent:

**A mutation whose text no longer matches the module it claims to patch.** It tests nothing, and the
harness that scored one of those as "no failure" is the reason this repo distrusts its own tools:
the thing built to find checks that cannot fail had exactly that defect, reporting a real rule as
untested while hiding a fake one. Asserted here rather than only inside the sweep, so a refactor
that moves a line turns the table red on the cheap job instead of on the slow one.

**A module with no table at all.** None of the eleven had one in the repo before this file existed,
and nine do now, which is exactly how the suite came to read as thorough: the modules that got
swept are thorough. So `TABLES` and `UNSWEPT` together have to account for every module in
`plugin/lib`, and a new module joins neither by accident.

`UNSWEPT` is deliberately a list of names rather than a count or a flag. A count drifts without
saying what changed, and a flag lets a module be quietly forgotten.

**A table file nothing assembles**, which is new since the tables became one file per module (#36).
The accounting above compares `plugin/lib` against `TABLES` and cannot see a file in `tables/` that
`tables/__init__.py` never imports - swept by nothing, with the mutations in it read as protection.
So that direction is checked too, both ways round.
"""

import contextlib
import io
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TESTS_PARTS = ("plugin", "tests")

import mutate  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def outside_sweep():
    """The environment with the sweep marker removed, for checks about ordinary `mutate.py` runs.

    This file runs inside the baseline copy as well as on its own, and the sweep sets the marker for
    everything it spawns, so a check that wants `mutate.py`'s ordinary behaviour cannot inherit the
    environment. See the use below `main`'s exit-status check for what happened when one did.

    Only for subprocesses. `run_main` calls `main` in-process and has to reach `os.environ` itself.
    """
    env = dict(os.environ)
    env.pop(mutate.SWEEPING, None)
    return env


print("every module in plugin/lib is accounted for")

modules = {path.stem for path in mutate.LIB.glob("*.py") if not path.stem.startswith("_")}
accounted = set(mutate.TABLES) | mutate.UNSWEPT
check("nothing in lib is missing from both TABLES and UNSWEPT", sorted(modules - accounted), [])
check("and neither names a module that no longer exists", sorted(accounted - modules), [])
# Both directions are needed. Without the second, deleting a module would leave a table pointing at
# a file that is gone, and the sweep does not survive that: it reads the source unguarded, so the
# job dies on an uncaught FileNotFoundError naming a path rather than a rule. Guarding the read was
# the alternative and is worse - it turns a deleted module into fifteen "mutation did not apply"
# lines on the slow job, all describing the wrong problem. Better to fail here, on the cheap one,
# saying which module went missing.
check(
    "a module is in one half or the other, never both",
    sorted(set(mutate.TABLES) & mutate.UNSWEPT),
    [],
)

# `UNSWEPT` is the union of two sets now, which the accounting above cannot see: a name in both
# would leave every check here green while the notes `targets` prints disagree with themselves
# about whether the module is owed or declined. Same reason the intersection above is checked.
check(
    "a module is either owed a table or declined one, never both",
    sorted(mutate.NOT_YET & set(mutate.DECLINED)),
    [],
)
check(
    "and UNSWEPT is exactly those two, so nothing is unswept without appearing in one of them",
    mutate.UNSWEPT,
    mutate.NOT_YET | set(mutate.DECLINED),
)
# The reason is the whole point of the split. A blank one turns a recorded decision back into the
# silent permanent entry on a debt list that the split exists to stop, and `targets` prints it into
# the sweep log, where an empty string reads as a tool bug rather than a choice.
check(
    "and a declined module says why, in words",
    sorted(name for name, why in mutate.DECLINED.items() if len(why.split()) < 4),
    [],
)

# The third direction, which only exists because the tables became files (#36). The two above
# compare `plugin/lib` against `TABLES`; neither can see a file in `tables/` that `__init__.py`
# forgot to import, and that file is swept by nothing and assembled by nothing while both checks
# stay green. `targets` reports the same thing for a changed file, but only for a changed one: a
# table added and never wired up is silent from the day after it lands.
TABLE_FILES = {
    path.stem for path in (HERE / "tables").glob("*.py") if path.stem not in {"__init__", "shape"}
}
check(
    "every file in tables is a table some module's sweep reads",
    sorted(TABLE_FILES - set(mutate.TABLES)),
    [],
)
check("and every table in TABLES is a file", sorted(set(mutate.TABLES) - TABLE_FILES), [])

print("every mutation still patches the source it claims to")

for name, table in sorted(mutate.TABLES.items()):
    source = (mutate.LIB / f"{name}.py").read_text(encoding="utf-8")
    check(f"{name} has at least one mutation", bool(table), True)
    for mutation in table:
        check(f"{name}: declared module matches its table", mutation.module, name)
        # Exactly one, not "at least one": a mutation hitting two places breaks two rules at once,
        # so the suite objecting says nothing about which of them is asserted.
        check(f"{name}: {mutation.rule!r} matches exactly once", source.count(mutation.old), 1)
        check(
            f"{name}: {mutation.rule!r} actually changes something",
            mutation.new != mutation.old,
            True,
        )
        check(
            f"{name}: {mutation.rule!r} names a test file that exists",
            (HERE / mutation.caught_by).is_file(),
            True,
        )

# Existing is not enough, and this file is the counterexample. `prepare` deletes everything in
# `UNSWEEPABLE` from the mutated copy, so a mutation naming one of those is caught by a file that is
# not there: it passes the check above, survives every sweep, and gets reported as a rule nothing
# asserts. A false survivor rather than a false catch, so it costs somebody an afternoon proving the
# rule is fine rather than shipping a hole - but the whole value of the summary is that a line in it
# means something, and the set claimed this in a comment with nothing holding it up.
#
# Relative to `plugin/tests` rather than by basename, because `caught_by` is resolved against that
# directory and the set holds repo-relative paths. The shape check further down - every entry sits
# directly in `plugin/tests` - makes the two the same thing for anything the set is allowed to hold,
# so this is not a fix for a live bug. It is the form that does not lean on that check being there.
UNSWEEPABLE_NAMES = {path.removeprefix("plugin/tests/") for path in mutate.UNSWEEPABLE}
# `prepare` unlinks each of these out of the copy, so a path that does not exist is a
# FileNotFoundError out of every sweep rather than a verdict - the crash-instead-of-a-report shape
# again, and out of the set rather than out of a module. Cheap gate first, so a wrong entry is one
# red line here instead of a traceback 191 times on the slow job.
check(
    "every path the sweep deletes is a path that exists",
    sorted(path for path in mutate.UNSWEEPABLE if not (mutate.REPO / path).is_file()),
    [],
)
# And the set has to still name this file, which is what `prepare` deleting it turns on. Emptying
# the set is a one-line edit that every check quantifying over the set is vacuously true of, and it
# stops `prepare` deleting anything: the mutated copies keep a file that fails by construction,
# every mutation reads as caught, `verdict`'s "the suite passed, so nothing asserts this rule"
# branch goes unreachable, and the sweep is clean and worthless. That is the defect `prepare`'s
# docstring records, and deriving the deletion from data moved it out of a diff a reviewer can see
# and into the contents of a set. The `prepare` check further down does go red on it, so this is not
# the only line between here and that outcome - but it goes red saying a mutated copy still has the
# file, which is the symptom three steps along, and this one says the set is empty.
#
# From `__file__` rather than typed out, so this is one fact and not a copy of one. `relpath` rather
# than `relative_to`, which raises rather than reports when the resolved file is not under `REPO`.
# That is the whole condition and the line above is all of it. Four wordings tried to say more than
# that - three as a list of arrangements, one as a looser restatement that made a file above `REPO`
# sound safe - and each was wrong. So: examples below, not a set. `mutate` on `PYTHONPATH` with this
# file run from outside the tree, and a symlinked `mutate.py` with `tables` beside it. Both probed,
# both red. With `relative_to` the same line raises `ValueError` and nothing after it in this file
# prints, which is the part worth knowing - not how much, because a count of that would re-label
# itself as checks are added, and `ci.yml` spends a paragraph on why that is the bug. Two
# arrangements cannot reach it, for one reason: a symlinked entry point resolves the import root
# along with the file, and a copied `plugin/` tree brings its own `mutate.py`, so `REPO` moves
# either way and the paths agree.
#
# Neither of the two that reach it is a supported way to run the suite - both die further down
# reading `run.py` from `HERE` - so what this buys is #42's rule, a red line rather than a
# traceback, and not a working run. In the two that cannot reach it this check passes: a symlinked
# entry point runs green end to end, and a copied `plugin/` tree fails one unrelated check because
# the suite reads above `plugin/`. Same reason this is a list rather than `in`: `got False, want
# True` does not say which path went missing after a rename.
SELF = os.path.relpath(pathlib.Path(__file__).resolve(), mutate.REPO)
check(
    "and the set names this file, which is the reason it exists",
    sorted(p for p in [pathlib.PurePath(SELF).as_posix()] if p not in mutate.UNSWEEPABLE),
    [],
)
# Shape as well as content, and `targets` only has wording for one shape: `plugin/tests/<file>.py`.
# An entry under `tables/` is deleted from every copy and comes back as a module to resweep, with no
# note that it cannot be swept. Anywhere else nested it is deleted from every copy and produces no
# module and no note at all, because the length test above the tests branch skips it - silent, which
# is worse than the misreport. Either way it is the direction the comment on the set does not cover.
check(
    "and every entry is a file directly in plugin/tests, which is the shape targets notes",
    sorted(p for p in mutate.UNSWEEPABLE if pathlib.PurePosixPath(p).parts[:-1] != TESTS_PARTS),
    [],
)
check(
    "and not one the sweep deletes from the copy it runs in",
    sorted(
        f"{name}: {mutation.rule}"
        for name, table in mutate.TABLES.items()
        for mutation in table
        if mutation.caught_by in UNSWEEPABLE_NAMES
    ),
    [],
)

print("and the harness refuses a mutation it cannot apply")

# The defect the throwaway harness had, asserted directly. Scoring a non-matching mutation as "no
# failure" is how it reported a real rule as untested while hiding a fake one.
sample = mutate.Mutation(
    module="hookio",
    rule="x",
    old="text that is not in any module",
    new="y",
    caught_by="test_hook.py",
)
check("a mutation matching nothing is refused", mutate.apply("abc", sample)[0], None)
check("and says why", "matched 0 times" in (mutate.apply("abc", sample)[1] or ""), True)

twice = mutate.Mutation(module="hookio", rule="x", old="ab", new="y", caught_by="test_hook.py")
check("a mutation matching twice is refused too", mutate.apply("ab ab", twice)[0], None)
check("and says how many", "matched 2 times" in (mutate.apply("ab ab", twice)[1] or ""), True)

# The ordinary direction still has to work, or every check above could be satisfied by an `apply`
# that refuses everything.
once = mutate.Mutation(module="hookio", rule="x", old="ab", new="cd", caught_by="test_hook.py")
check("and a single match is applied", mutate.apply("ab", once), ("cd", None))

print("and it scores a finished run the way it claims to")

# The part with the history. All three defects this harness has had were in the scoring rather than
# the running - a mutation that did not apply scored as a pass, a suite that could not pass scored
# as a catch, a file failing by construction scored as the catcher - and all three were invisible
# because scoring had no seam. Fed synthetic runner output here, so deleting the `caught_by`
# comparison or the baseline refusal is a red build on the cheap job rather than a silent loss on
# the slow one.
# A failing check inside the section, not just the runner's summary line. Those are two different
# signals and the scoring told them apart only from #42 onwards: `run.py` reports any non-zero child
# in `FAILED:`, and a file that dies on a traceback is non-zero, so a fixture with no `FAIL` line in
# it is a file that crashed rather than one that objected. `CRASHED` is that case, kept beside this
# one because the pair is the whole distinction.
CAUGHT = "=== test_hook.py\n  FAIL  a rule nobody kept: got 1, want 2\nFAILED: test_hook.py\n"
CRASHED = (
    "=== test_hook.py\n"
    "  ok    the checks before the crash\n"
    "Traceback (most recent call last):\n"
    "TypeError: argument of type 'NoneType' is not iterable\n"
    "FAILED: test_hook.py\n"
)

check(
    "a suite that passed means the rule is unasserted",
    mutate.verdict(0, "everything passed\n", once)[0],
    False,
)
check(
    "and says that, rather than something about the mutation",
    "nothing asserts this rule" in mutate.verdict(0, "everything passed\n", once)[1],
    True,
)
check(
    "a failure from the named file is a catch",
    mutate.verdict(1, CAUGHT, once),
    (True, "test_hook.py"),
)
check(
    "a failure from some other file is not",
    mutate.verdict(1, "FAILED: test_store_claims.py\n", once)[0],
    False,
)
check(
    "and names both, because which file caught it is the finding",
    mutate.verdict(1, "FAILED: test_store_claims.py\n", once)[1],
    "caught by test_store_claims.py rather than test_hook.py",
)
check(
    "a named file among others still counts",
    mutate.verdict(1, "FAILED: test_store_claims.py, test_hook.py\n", once)[0],
    True,
)
# First in the list as well as last, because those are different bugs and only one of them was
# covered. `split(",")` reduced to `split()` leaves the trailing comma on every name but the last,
# so a mutation caught by the first file named is reported as caught by something else - a survivor
# for a rule that was asserted, which is the error nobody chases down. Green until this line.
check(
    "and the position it is named in does not change the answer",
    mutate.verdict(1, "FAILED: test_hook.py, test_store_claims.py\n", once)[0],
    True,
)
check(
    "a failure naming no file is the runner breaking, not a catch",
    mutate.verdict(1, "Traceback (most recent call last):\n", once)[0],
    False,
)
# The whole reason `run_suite` captures stderr. A branch that captures the reason and then reports a
# fixed string is the capture not being there, which is what this did until the second review pass.
check(
    "and it passes on the reason, since there is no file name to report",
    "RuntimeError: died" in mutate.verdict(1, "Traceback:\nRuntimeError: died\n", once)[1],
    True,
)
check(
    "and a run that never happened is not a catch either",
    mutate.verdict(None, "the suite hung", once),
    (False, "the suite hung"),
)

# The baseline is the load-bearing half: without it every mutation scores as caught, which is how
# the first version of this file reported thirteen catches with its survivor branch unreachable.
check("a passing baseline is usable", mutate.baseline_verdict(0, "everything passed\n"), None)
check(
    "a failing baseline is refused",
    "no mutation result means anything" in (mutate.baseline_verdict(1, CAUGHT) or ""),
    True,
)
check(
    "and it names the file that failed",
    "test_hook.py" in (mutate.baseline_verdict(1, CAUGHT) or ""),
    True,
)
check(
    "a baseline that could not run at all is refused too",
    "could not be run" in (mutate.baseline_verdict(None, "the suite hung") or ""),
    True,
)
# The branch that runs when the baseline dies rather than fails, which is when somebody most needs
# the message, and the only new scoring branch that had no check after the first review pass.
check(
    "a baseline that died says why, since it named no file",
    "RuntimeError: died" in (mutate.baseline_verdict(1, "Traceback:\nRuntimeError: died\n") or ""),
    True,
)
check(
    "and it survives a run that printed nothing at all",
    "no output at all" in (mutate.baseline_verdict(1, "") or ""),
    True,
)

print("and it can tell a file that objected from a file that died")

# `sections` is why #42 is answerable at all: the runner's summary says which files failed and
# nothing more, so deciding whether the named file objected means reading that file's own output and
# nobody could, because the output was one string.
#
# Read with `sorted(..., key=repr)` and `.get`, neither of which is fussiness. The first version of
# these three checks used plain `sorted` and a plain index, and both die on exactly the output a
# broken `sections` produces: `sorted` on a dict holding a `None` key raises TypeError comparing it
# with a string, and the index raises KeyError when the split collapses to one bucket. Either kills
# this file at the check that was supposed to report the defect and takes the two hundred checks
# after it with it, which is #42's failure mode inside the gate that exists to catch #42.
TWO_FILES = CAUGHT + "=== test_store_claims.py\n  ok    fine\n"
check(
    "output splits on the headers the runner prints",
    sorted(mutate.sections(TWO_FILES), key=repr),
    ["test_hook.py", "test_store_claims.py"],
)
check(
    "and a section is the lines under its header, not the whole run",
    "FAIL" in mutate.sections(TWO_FILES).get("test_store_claims.py", ""),
    False,
)
# Anything before the first header belongs to no file. It is the runner's own preamble, and
# attaching it to the first file makes that file answer for text it did not print.
#
# Compared as a whole dict rather than by key, so both shapes of the defect land here: a `None`
# bucket holding the preamble, and the preamble prepended to the first real file.
check(
    "and a preamble before any header belongs to no file",
    mutate.sections("running 9 files\n" + CAUGHT),
    {"test_hook.py": "  FAIL  a rule nobody kept: got 1, want 2\nFAILED: test_hook.py"},
)
# A file announced and then silent is the shape a crash in the first check leaves behind, and it is
# the one case where the header alone has to create the section. Without it the name is simply
# absent, which `failed_a_check` reads as "printed nothing", so the answer comes out the same by
# accident - and stops doing so the moment anything else asks what the sweep saw.
check(
    "a file announced and then silent is still a section of its own",
    mutate.sections("=== test_hook.py\n"),
    {"test_hook.py": ""},
)
# Deliberately not `FAILED:`, which is the obvious thing to look for and the wrong one: the runner
# prints it after the last section's header, so it lands inside that file's section and every crash
# in the last file swept would read as a check failing.
check("a section with a failing check says so", mutate.failed_a_check(CAUGHT, "test_hook.py"), True)
check("one that only died does not", mutate.failed_a_check(CRASHED, "test_hook.py"), False)
check(
    "and the summary line is not a failing check, whichever section it fell into",
    mutate.failed_a_check("=== test_hook.py\nFAILED: test_hook.py\n", "test_hook.py"),
    False,
)
check(
    "a file that printed nothing at all did not fail a check",
    mutate.failed_a_check(CAUGHT, "test_store_claims.py"),
    False,
)

print("and each of those verdicts is what the sweep actually asks for")


# Found the same way as everything else here, by breaking it: replacing `baseline`'s body with
# `return None` left the whole suite green, and a baseline that never refuses is the exact defect
# `baseline` was added to fix, scoring every mutation as caught. The scoring got asserted above and
# the two-line functions that call it did not, which is the seam problem one step further out.
def through(result, call):
    """Run `call` with `run_suite` stubbed, since these two functions are only wiring.

    `through.handed` is every call the stub took, as `(mutation, only)`, and it is recorded because
    a stub with defaulted parameters answers `run_suite()` and `run_suite(mutation)` alike, so the
    return value alone says nothing about which call the wiring makes. Dropping the argument in
    `sweep_one` sweeps an unpatched copy for every entry, which the baseline has just proved passes,
    so every one of them comes back as "the suite passed, so nothing asserts this rule". Red, but
    naming the whole table as unasserted when the defect is one argument.

    A list rather than the last call, since #43 made `sweep_one` run the suite either once or twice
    and which of those it did is the whole of that change. The last call alone cannot tell a catch
    that stopped after one narrow run from one that went on to run everything: both end on a call
    that reaches the same verdict, and the second costs the fourteen files the issue was about.
    """
    real = mutate.run_suite
    through.handed = []

    def stub(mutation=None, only=None):
        through.handed.append((mutation, only))
        return result

    mutate.run_suite = stub
    try:
        return call()
    finally:
        mutate.run_suite = real


check(
    "baseline asks baseline_verdict, rather than answering for itself",
    "no mutation result means anything" in (through((1, CAUGHT), mutate.baseline) or ""),
    True,
)
check(
    "and passes a clean run through unchanged",
    through((0, "everything passed\n"), mutate.baseline),
    None,
)
check(
    "having asked for no mutation, which is the whole point of it", through.handed, [(None, None)]
)
check(
    "sweep_one asks verdict, and reports the mutation it was given",
    through((1, "FAILED: test_store_claims.py\n"), lambda: mutate.sweep_one(once)),
    (False, "caught by test_store_claims.py rather than test_hook.py", False),
)
check(
    "and asked for that mutation rather than for a clean run",
    [mutation for mutation, _ in through.handed],
    [once, once],
)
# The third value, which is #42. Both of these are `verdict` saying caught, and the difference
# between them is entirely inside the named file's own output: one printed a failing check and the
# other printed a traceback. Scored the same until this branch existed, so a file that dies a third
# of the way in stopped asserting everything after that point while the sweep reported it as the
# catcher of every rule it names.
check(
    "a catch whose file printed a failing check is an ordinary catch",
    through((1, CAUGHT), lambda: mutate.sweep_one(once)),
    (True, "test_hook.py", False),
)
check(
    "a catch whose file only died is flagged instead",
    through((1, CRASHED), lambda: mutate.sweep_one(once))[2],
    True,
)
check(
    "and says so, since the mutation is not what is wrong",
    "died rather than objecting" in through((1, CRASHED), lambda: mutate.sweep_one(once))[1],
    True,
)
# The flag is about the file the mutation names, not about any file failing. A crash in `store`
# while `hook` objects properly is `store`'s problem and says nothing about this rule, and the
# cheapest way to get this wrong is to scan the whole output for `FAIL`.
check(
    "a check failing in some other file does not clear the flag",
    through(
        (1, CRASHED + "=== test_store_claims.py\n  FAIL  something else\n"),
        lambda: mutate.sweep_one(once),
    )[2],
    True,
)
# A survivor is never flagged, because there is nothing to explain: the suite passed, so no file
# failed at all and "it died rather than objecting" would be a wrong reason for a right verdict.
check(
    "and a rule nothing asserts is not a crash",
    through((0, "everything passed\n"), lambda: mutate.sweep_one(once)),
    (False, "the suite passed, so nothing asserts this rule", False),
)

print("and it pays for the whole suite only when one file cannot answer")

# #43, and two failure modes that every other check in this file is green for. Dropping `only` is
# correct and slow: the verdicts are unchanged, so nothing reports anything, and the sweep goes back
# to fourteen files per mutation - 2913 seconds for 244 of them, against a suite of nine. Dropping
# the second run is fast and wrong, because a survivor, a crash and a mis-attribution are all
# questions about the files the first run left out.
through((1, CAUGHT), lambda: mutate.sweep_one(once))
check(
    "a file that objects is asked on its own, and nothing else is run at all",
    through.handed,
    [(once, "test_hook.py")],
)
for outcome, what in (
    ((0, "everything passed\n"), "a survivor"),
    ((1, CRASHED), "a file that only died"),
    ((1, "FAILED: test_store_claims.py\n"), "a catch some other file made"),
):
    through(outcome, lambda: mutate.sweep_one(once))
    check(
        f"{what} goes on to the whole suite, the answer being in the files it skipped",
        through.handed,
        [(once, "test_hook.py"), (once, None)],
    )

print("and what run_suite hands it is what the scoring needs")

# The other side of that seam, which `through` stubs out everywhere above and so nothing asserted at
# all. Three returns, two of them probed green: cutting the return down to `done.stdout` alone, and
# narrowing `except subprocess.TimeoutExpired` to an exception the call cannot raise. Both are the
# reason a reader gets rather than the verdict - with stdout only, a suite that died reports
# `=== test_hook.py` as the cause of death - and `last_line`'s own docstring says a branch that
# captures the reason and then reports something fixed is the capture not being there.


class Finished:
    """What `subprocess.run` hands back, which is all `run_suite` reads of it."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def ran(outcome, mutation=None, only=None):
    """`run_suite` with the subprocess stubbed. Costs a repo copy rather than a suite run.

    A timeout that escapes is turned into a value rather than left to propagate, for the same reason
    `test_hook.py` catches the pty one: narrowing the `except` in `run_suite` otherwise kills this
    file mid-run, and a test that dies names nothing while a failed check names itself.

    `ran.patched` is the lib modules in the scratch copy whose text differs from the real one, read
    inside the stub because the copy is deleted the moment `run_suite` returns. That is the only way
    to see the read side from here: the scratch path never leaves the function.
    """
    real = mutate.subprocess.run
    ran.patched = "the suite was never launched"
    # What `run_suite` passed the subprocess, which is where the sweep marker gets into the child.
    ran.kwargs = {}
    # And the command line, which is where the one-file selection gets there.
    ran.args = []

    def stub(args, **kwargs):
        ran.kwargs = dict(kwargs)
        ran.args = list(args)
        scratch = pathlib.Path(args[1]).parents[2]
        ran.patched = sorted(
            path.name
            for path in (scratch / "plugin" / "lib").glob("*.py")
            if path.read_text(encoding="utf-8")
            != (mutate.LIB / path.name).read_text(encoding="utf-8")
        )
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    mutate.subprocess.run = stub
    try:
        return mutate.run_suite(mutation, only=only)
    except subprocess.TimeoutExpired:
        return "it propagated", "the timeout escaped run_suite rather than being reported"
    finally:
        mutate.subprocess.run = real


# A status no scoring branch can produce by accident. With `Finished(1, ...)` this check read as an
# assertion and was not one: `return 1, done.stdout + done.stderr` is indistinguishable from reading
# the process's status, which is the two-inputs-that-agree defect the `prepare` fixture below is
# deliberately built to avoid, reproduced here by picking the obvious fixture value.
code, out = ran(Finished(7, "=== test_hook.py\n", "RuntimeError: the runner itself died\n"))
check("a run's exit status comes back as the process reported it", code, 7)
check(
    "and its stderr with its stdout, since a suite that died says why only there",
    out.splitlines(),
    ["=== test_hook.py", "RuntimeError: the runner itself died"],
)

hung = ran(subprocess.TimeoutExpired(cmd="run.py", timeout=120))
check("a suite that hung is no result rather than a failure", hung[0], None)
check("and says that is what happened, since it named no file", "hung" in hung[1], True)

# The read side, which every check above leaves out: they call `run_suite` with no mutation, so
# `source = LIB / f"{mutation.module}.py"` is never evaluated and hardcoding `hookio.py` there stays
# green. A real table entry rather than the synthetic one, because the read has to find the `old`
# text to get as far as the copy at all, and `store` rather than `hookio` for the same reason the
# `prepare` fixture below is `store`: two inputs that agree cannot say which one was read.
#
# One check rather than three. "The run still came back" repeats the exit-status check above with a
# weaker fixture, and "no mutation patches nothing" has no failure mode that is not a crash first:
# every way of making a mutation-less `run_suite` write a module reads `None.py` or calls
# `write_text(None)` and dies naming a path. The baseline asking for no mutation is asserted from
# the other side of the seam, in `through` above.
ran(Finished(0, "everything passed\n", ""), mutate.TABLES["store"][0])
check("a mutation is read out of the module it names", ran.patched, ["store.py"])

# The selection, which every check above defaults away and which `sweep_one`'s first run is entirely
# about. `run.py` takes file names positionally, so handing it one and handing it none are one list
# element apart, and a `run_suite` that accepts `only` and never puts it on the command line runs
# the whole suite twice per mutation while reporting exactly what it reports now.
ran(Finished(0, "everything passed\n", ""), mutate.TABLES["store"][0], only="test_cli.py")
check("the one file asked for is the one the runner is told to run", ran.args[2:], ["test_cli.py"])
# And the other direction, because a command line that always names something cannot run the suite:
# `sweep_one`'s second run, `baseline` and the manual invocation all pass nothing and mean all of
# them.
ran(Finished(0, "everything passed\n", ""), mutate.TABLES["store"][0])
check("and no selection names no file, which run.py reads as all of them", ran.args[2:], [])


# The refusal that is the harness's original defect, one function in from the `apply` checks above:
# drop it and `prepare` is handed `mutated=None`, copies the repo unpatched, and a table entry that
# has merely drifted gets reported as a rule nothing asserts.
#
# Asserted through a stub that objects to being called, because "before anything runs" is half the
# claim and because the plain version passed for the wrong reason. Dropping the refusal leaves
# `test_mutations.py` in the copy, since `prepare` only removes it when there is a mutation, so the
# suite it launches re-enters this file and calls this line again. What came back at the top was a
# 120-second timeout rather than a pass: a green check with nested recursion underneath it.
def without_running(mutation):
    """`run_suite`, with a subprocess that reports having been reached at all."""
    real = mutate.subprocess.run

    def stub(*args, **kwargs):
        raise AssertionError("the suite was run for a mutation that did not apply")

    mutate.subprocess.run = stub
    try:
        return mutate.run_suite(mutation)
    except AssertionError as exc:
        return "it ran anyway", str(exc)
    finally:
        mutate.subprocess.run = real


code, why = without_running(sample)
check("a mutation that will not apply is refused before any suite runs", code, None)
check("and says the mutation was the problem, not the rule", "mutation did not apply" in why, True)

print("and it refuses a mutation that is not a program")

# One step past "assert the replacement happened": a typo in a table entry stops the module
# importing, every test file touching it fails, the named one is among them, and the sweep scores a
# catch for a rule nothing exercised.
broken = mutate.Mutation(
    module="hookio",
    rule="x",
    old="def f(value):",
    new="def f(value)",
    caught_by="test_hook.py",
)
mutated, problem = mutate.apply("def f(value):\n    return value\n", broken)
check("a mutation that does not parse is refused", mutated, None)
check("and says what is wrong with it", "does not parse" in (problem or ""), True)

print("and it turns those verdicts into the exit code CI actually reads")

# The seam the last round added stopped one step short. Scoring became assertable and got asserted,
# while the wiring from a verdict to an exit status did not, and that wiring is the whole contract
# with the `mutate` job: nothing else in this repo looks at the sweep's output. Probed rather than
# assumed - changing the survivors branch from `return 1` to `return 0` printed "1 mutation(s)
# survived", named the live rule, and exited 0, with the full suite green. A gate that reports a
# finding and passes anyway is the failure mode this project is named for.
#
# Stubbed rather than swept, because the point is the arithmetic around the calls and a real sweep
# costs a suite run each. `main` reads `baseline` and `sweep_one` as module globals, which is the
# seam.
ONE = mutate.Mutation(
    module="hookio", rule="stub", old="whatever", new="whatever else", caught_by="test_hook.py"
)


def run_main(argv, *, tables, caught, crashed=False, baseline_problem=None, changed=None):
    """`main`'s exit code and what it printed, with the two slow calls stubbed.

    `changed` stubs `changed_since` for the `--since` checks, as `(paths, problem)`. Stubbed rather
    than driven off this repository's real history: the answer would then depend on what the branch
    happens to contain, so the check that says "a change to a doc sweeps nothing" would pass or fail
    by accident. The git call has its own checks further down.
    """
    real = (mutate.TABLES, mutate.baseline, mutate.sweep_one, mutate.changed_since)
    mutate.TABLES = tables
    mutate.baseline = lambda: baseline_problem
    mutate.sweep_one = lambda mutation: (caught, "stubbed", crashed)
    if changed is not None:
        mutate.changed_since = lambda base: changed
    # `main` reads the sweep marker from the real `os.environ`, and this calls it in-process rather
    # than spawning it, so the copied dict `outside_sweep` returns cannot reach it. Inside the
    # baseline copy the marker is set, and without this every check below got the re-entrancy
    # refusal's exit 2 instead of the arithmetic it was written for. Fourteen of them at once, and
    # `baseline` is what said so.
    marker = os.environ.pop(mutate.SWEEPING, None)
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            return mutate.main(argv), printed.getvalue()
    finally:
        mutate.TABLES, mutate.baseline, mutate.sweep_one, mutate.changed_since = real
        if marker is not None:
            os.environ[mutate.SWEEPING] = marker


# Two modules and two mutations each, not one of each, and the output is read rather than only the
# exit code. Both matter and both were missing: with a single-entry table, a loop that visits one
# mutation per module or ignores the argv filter entirely produces the same exit code as a correct
# one. Probed on the real thing - slicing the inner loop swept 3 of 16 and printed "every one of
# 16", and dropping the filter swept all 16 for `mutate.py hookio` and printed "every one of 8".
# Both green. The count is all the reader gets, so the count is what has to be asserted.
TWO = {"hookio": [ONE, ONE], "store": [ONE, ONE]}

code, printed = run_main([], tables=TWO, caught=True)
check("every mutation caught is a pass", code, 0)
check("and the summary counts both modules' worth", "every one of 4 mutation" in printed, True)
# Named for what it asserts, which is less than it used to claim. Reverting `scored += 1` to
# `sum(len(TABLES[name]) for name in wanted)` - the exact form the comment in `mutate.py` warns
# against - leaves this green, because under a stub the loop calls `sweep_one` once per table entry
# and work done and table length cannot diverge. What catches that reversion is the pair below: a
# sliced loop and a dropped argv filter both make them diverge, and both are red. So the counter
# stays, for the case where a skip path gets added and nobody re-derives this.

code, printed = run_main(["hookio"], tables=TWO, caught=True)
check("a named module is a pass too", code, 0)
check(
    "and its count is the one module's, not the whole table's",
    "every one of 2 mutation" in printed,
    True,
)

check("and each catch says which file objected", "stubbed" in printed, True)
check("and nothing on a clean run is marked alive", "ALIVE" in printed, False)
# The third state of the marker column, which had no check while the other two did. `ALIVE` and
# `crash` were asserted and `ok` was not, so rewriting the expression to mark a catch `crash` left
# the suite green: every mutation printed `crash` above a summary reporting no crashes and saying
# every one was caught. A run contradicting itself is what the column exists to prevent, and saying
# so about two of three states is not saying it.
check("and a catch is marked ok, which is the third state", "ok    stub" in printed, True)
check("and not as a crash, on a run that had none", "crash" in printed, False)

# The detail, in every one of these, not just the exit code. `mutate.py`'s own summary comment says
# the detail is the load-bearing half, because `ALIVE` covers four different outcomes and only one
# of them is a finding - and then nothing asserted it, so deleting the line that prints it left
# the suite green. The exit code tells CI; the text tells the person who has to act on it.
code, printed = run_main([], tables=TWO, caught=False)
check("a survivor is a failure, however it is reported", code, 1)
# Read off the text after the `survived:` line, not off the whole run. Looking anywhere in the
# output found the rule and the detail in the `ALIVE` lines further up, so the summary block
# this file's own comment calls "what gets read" could be deleted entirely with the suite green -
# both the detail line and the whole `for` body, probed separately. The summary is the part a person
# scrolls back to; the per-mutation lines are buried in twenty others.
#
# And the split is asserted before anything is read off it, because `[-1]` on a string with no
# separator in it is the whole string: reword the `survived:` header and these two checks quietly go
# back to reading the entire run, which is the state they were in one pass ago. A seam that makes a
# check honest is itself a seam.
summary = printed.split("survived:")[-1]
check("a survivor run says so in a line of its own", summary != printed, True)
check("and the summary at the end names the module and the rule", "hookio: stub" in summary, True)
check("and carries the detail, which is which of four outcomes it was", "stubbed" in summary, True)
# The marker column, which is what a reader scans before reading anything. Collapsing it to a
# constant `ok` was green: the exit code and the summary still reported the survivor, so the run
# contradicted itself, every mutation marked `ok` above a summary saying one was alive.
check("and the mutation itself was marked alive, not ok", "ALIVE stub" in printed, True)

code, printed = run_main([], tables=TWO, caught=True, baseline_problem="the copy already fails")
check("a baseline that cannot be trusted stops the run rather than passing it", code, 2)
check("and says what was wrong with it", "the copy already fails" in printed, True)

# The crash tally, #42's other half. A crash is still a catch, so the run passes: the mutation was
# noticed, and what the flag says is that the file noticing it stopped early, so every rule it
# asserts after that point went unchecked this time round. That is a thing to go and look at rather
# than a reason to fail the build, and calling it a survivor would report a rule as unasserted when
# the table entry is fine.
code, printed = run_main([], tables=TWO, caught=True, crashed=True)
check("a catch by crashing still passes, since the mutation was caught", code, 0)
check(
    "but the run says how many, rather than burying it in the per-line output",
    "4 mutation(s) were caught by a file dying" in printed,
    True,
)
check(
    "and names them, since the file to go and look at is the finding",
    "hookio: stub" in printed,
    True,
)
# Same reason as the survivor marker above: a column that reads `ok` for all four outcomes is a run
# that contradicts its own summary.
check("and each one is marked crash rather than ok", "crash stub" in printed, True)
check(
    "a clean run reports no crashes at all",
    "caught by a file dying" in run_main([], tables=TWO, caught=True)[1],
    False,
)

# The cost line, which is the cheap half of #43: the sweep's own runtime, printed by the sweep,
# because the number that decides whether the next table is affordable is seconds per mutation and
# until this line the only place it existed was a human dividing a CI job's wall clock by a count in
# the summary. Asserted for the shape rather than the value, since the value is a real clock.
check(
    "a run reports what it cost",
    "4 mutation(s) in " in run_main([], tables=TWO, caught=True)[1],
    True,
)
check(
    "and the per-mutation figure, which is the one that scales",
    "s each" in run_main([], tables=TWO, caught=True)[1],
    True,
)

# Reachable without anyone meaning it: move the tables into `UNSWEPT` and the accounting above still
# balances, so a sweep that swept nothing would report "every one of 0 mutation(s) was caught".
code, printed = run_main([], tables={}, caught=True)
check("sweeping nothing is not a pass", code, 1)
check("and says so rather than reporting zero of zero", "proves nothing" in printed, True)

code, printed = run_main(["nosuchmodule"], tables=TWO, caught=True)
check("and a module with no table is an error, not an empty success", code, 2)
check("and names the module it has nothing for", "nosuchmodule" in printed, True)

print("and `--since` picks the modules a change could have broken")

# Two modules with different catchers, because the mapping is the whole question and a single-module
# table cannot tell a derivation that reads `caught_by` from one that returns everything.
MAPPED = {
    "hookio": [ONE],
    "store": [ONE._replace(module="store", caught_by="test_store_claims.py")],
}


def targets_with(paths, not_yet=None, declined=None):
    """`targets` against fixtures rather than against the real tables and the real debt list.

    The debt lists are swapped for the same reason `TABLES` is: they are meant to empty out. Keyed
    on a real member, the two checks below stop being able to fail the moment the last table owed
    under #8 is written, and what they would report then is a pass.
    """
    real = (mutate.TABLES, mutate.NOT_YET, mutate.DECLINED)
    mutate.TABLES = MAPPED
    mutate.NOT_YET = {"notyet"} if not_yet is None else not_yet
    mutate.DECLINED = (
        {"declined": "asserted here, not read from the real reason"}
        if declined is None
        else declined
    )
    try:
        return mutate.targets(paths)
    finally:
        mutate.TABLES, mutate.NOT_YET, mutate.DECLINED = real


check("a changed lib module is swept", targets_with(["plugin/lib/hookio.py"]), (["hookio"], []))
# The load-bearing half, and the one a narrowing written the obvious way would get wrong. The sweep
# asserts that the suite objects, so the way a mutation stops being caught is a check deleted from a
# test file - and that diff touches nothing under `plugin/lib` at all.
check(
    "and so is the module whose catcher changed, which is how a gate actually gets weakened",
    targets_with(["plugin/tests/test_store_claims.py"]),
    (["store"], []),
)
check(
    "and each module once, however many of its files changed",
    targets_with(["plugin/lib/hookio.py", "plugin/tests/test_hook.py"])[0],
    ["hookio"],
)
check(
    "a change the sweep cannot measure selects nothing",
    targets_with(
        [".github/workflows/ci.yml", "README.md", "plugin/hooks-handlers/session-start.sh"]
    ),
    ([], []),
)
# `test_cli.py` was here twice over, first as `([], [])` - #24 written down as a rule, silence about
# a changed test file nothing measures - then as a note saying no table maps it. Both described the
# mechanism correctly and the file wrongly: it is no mutation's `caught_by`, but it drives every
# command end to end, so it is one of the files most able to catch a mutation in any module, and a
# change to it that stops catching something narrowed to nothing being swept. That is #27, and what
# made it affordable to fix was #36 making the wide sweep rare rather than the default.
check(
    "a test file that catches across modules resweeps everything",
    targets_with(["plugin/tests/test_cli.py"])[0],
    ["hookio", "store"],
)
check(
    "and says which file, and that catching broadly is the reason",
    targets_with(["plugin/tests/test_cli.py"])[1],
    ["test_cli.py catches mutations across every module, so every table is reswept (#27)"],
)
# The shape filter is three conditions and the probe found two of them deletable: with the `plugin`
# test or the extension test gone, nothing in the suite objected. Both are the same failure, a path
# that only looks like a module picking one - a vendored tree with its own `lib/` and `tests/`, a
# note or a fixture sitting beside the module it is about - and the result is a sweep of a module
# this change never touched, which reads as cover it is not.
check(
    "a module-shaped path somewhere else selects nothing",
    targets_with(["vendor/lib/hookio.py", "elsewhere/tests/test_store_claims.py"]),
    ([], []),
)
check(
    "and neither does a file beside a module that is not the module",
    targets_with(["plugin/lib/hookio.md"]),
    ([], []),
)
# Narrowing has to stop when the thing doing the narrowing moves: every verdict in the last sweep
# was produced by this file and `run.py`, so a change to either makes all of them stale at once.
modules, notes = targets_with(["plugin/tests/mutate.py"])
check("a change to the instrument reswept everything", modules, ["hookio", "store"])
check("and says that is why", "instrument" in " ".join(notes), True)
check(
    "and so does a change to what the suite means",
    targets_with(["plugin/tests/run.py"])[0],
    ["hookio", "store"],
)
# The two entries #36 added, and the only reason splitting the tables out is safe. `shape.py`
# decides what a table entry is and `__init__.py` decides which tables exist, so either can
# invalidate every verdict at once. Neither had a check: deleting both lines from `INSTRUMENT` left
# the whole suite green, and a change to `__init__.py` then selected no modules at all and printed
# "is no module's table, so nothing assembles or sweeps it" about the file that assembles every
# table. Narrowing to nothing, with a false note over it, in the two files the split's safety
# argument rests on.
check(
    "a change to which tables exist resweeps all of them",
    targets_with(["plugin/tests/tables/__init__.py"])[0],
    ["hookio", "store"],
)
check(
    "and says the instrument changed, not that the file is nobody's table",
    targets_with(["plugin/tests/tables/__init__.py"])[1],
    ["the sweep's own instrument changed, so every table is reswept"],
)
check(
    "and so does a change to what a table entry is",
    targets_with(["plugin/tests/tables/shape.py"]),
    (["hookio", "store"], ["the sweep's own instrument changed, so every table is reswept"]),
)

# An unswept module has to leave a line behind. Silence here is a PR whose only changed module was
# never swept by anything, reported as a clean sweep, which is this repo's whole subject.
modules, notes = targets_with(["plugin/lib/declined.py"])
check("a declined module selects nothing", modules, [])
check("but says it was declined, and why", "deliberately not swept" in " ".join(notes), True)
check(
    "and the reason is the one on the entry, not a generic line", "asserted here" in notes[0], True
)
modules, notes = targets_with(["plugin/lib/notyet.py"])
check("a module still owed a table selects nothing", modules, [])
check("and says the change went unswept", "goes unswept" in " ".join(notes), True)

# The route that is the whole of #36. A table file names its module in its path, which is why the
# tables are nine files rather than one: a single `tables.py` could only ever be swept wide, because
# no path says which table inside a file changed, and the narrowing would have moved code without
# narrowing anything. Adding a mutation is the commonest diff in this repo and it now costs one
# module's sweep.
check(
    "a changed table sweeps the module it is the table for",
    targets_with(["plugin/tests/tables/store.py"]),
    (["store"], []),
)
check(
    "and not the whole package, which is what putting them in one file would have cost",
    targets_with(["plugin/tests/tables/store.py"])[0],
    ["store"],
)
# A table file for nothing is a file nobody runs. `__init__.py` imports the nine by name, so a tenth
# sitting beside them is assembled by nothing and swept by nothing, and the failure is silence. The
# accounting at the top of this file covers the opposite direction, a module with no table.
modules, notes = targets_with(["plugin/tests/tables/nosuch.py"])
check("a table file no module claims selects nothing", modules, [])
check(
    "but says nothing assembles it, since a table nobody runs is the silent case",
    "is no module's table" in " ".join(notes),
    True,
)
# Both halves of a wide run's output. The notes are how an unswept or unmapped module gets reported,
# and returning early on the wide path dropped them: the sweep would sweep everything, correctly,
# and say nothing about the module in the same diff that no table covers.
modules, notes = targets_with(["plugin/tests/mutate.py", "plugin/lib/notyet.py"])
check("a wide sweep is still wide when something unswept changed too", modules, ["hookio", "store"])
check(
    "and reports the wide reason first, since it is why the run looks like that",
    "instrument" in notes[0],
    True,
)
check("and still says the unswept module went unswept", "goes unswept" in " ".join(notes), True)

# The same hole one step over, and the one that shipped: a changed test file no `caught_by` names
# mapped to nothing and said nothing, so a diff that added a whole test file printed "nothing that a
# sweep can measure changed". The first of these two could not have failed before; the second is the
# fix. `test_handlers.py` is the permanent instance, the handlers being shell.
modules, notes = targets_with(["plugin/tests/test_store_claims.py"])
check("a test file a mutation names selects its module", modules, ["store"])
check("and says nothing, because it was measured", notes, [])
modules, notes = targets_with(["plugin/tests/test_handlers.py"])
check("a test file no mutation names selects nothing", modules, [])
check("but says no table maps it", "named by no mutation" in " ".join(notes), True)
check("and names the file, not just the fact", "test_handlers.py" in " ".join(notes), True)
# The third wording, for the file the sweep deletes from every copy it makes. Without it this said
# "named by no mutation, so no table maps this change" about `test_mutations.py`, which reads as a
# table nobody has written when what it actually is is a file no mutation is allowed to name - and
# on a harness PR it printed next to "every table is reswept", which is the contradictory pair the
# `INSTRUMENT` skip exists to stop.
modules, notes = targets_with(["plugin/tests/test_mutations.py"])
check("the file the sweep deletes from every copy selects nothing", modules, [])
check(
    "and says that is why, rather than that a table is owed",
    notes,
    ["test_mutations.py is deleted from every mutated copy, so no mutation can name it"],
)

docs = (["README.md"], None)
code, printed = run_main(["--since", "main"], tables=TWO, caught=True, changed=docs)
check("a change with nothing to sweep is a pass, not a refusal", code, 0)
check("and says so in its own words", "nothing that a sweep can measure" in printed, True)
# The one thing this must never be mistaken for. `no mutations to sweep, which proves nothing` is
# exit 1 and means a sweep was asked to prove something and could not; this is exit 0 and means
# there was nothing to ask. Same output would make the two indistinguishable in a log.
check("and not by claiming a sweep happened", "every one of" in printed, False)
check("and not by the refusal that means the opposite", "proves nothing" in printed, False)

code, printed = run_main(
    ["--since", "main"], tables=TWO, caught=True, changed=(["plugin/lib/hookio.py"], None)
)
check("a change under lib sweeps that module", code, 0)
check("and only that module, which is the entire point", "every one of 2 mutation" in printed, True)

code, printed = run_main(
    ["--since", "nope"],
    tables=TWO,
    caught=True,
    changed=(None, "no merge base for 'nope' and HEAD"),
)
check("a ref git cannot answer for stops the run", code, 2)
check("and does not pass as an empty diff", "refusing to sweep" in printed, True)
check("and says what git said", "no merge base" in printed, True)

code, printed = run_main(["--since"], tables=TWO, caught=True)
check("--since with no ref is an error", code, 2)
check("and says what is missing rather than dying on the index", "needs a ref" in printed, True)
# The message, not only the status, and that is what the check was missing. CI passes this in from
# `github.event.before`, which can arrive empty, and with the `strip` gone the empty string reaches
# git, fails at `merge-base`, and exits 2 as well - the same status from a refusal about the wrong
# thing, reading `no merge base for '  '` when the answer is that nothing was passed.
code, printed = run_main(["--since", "  "], tables=TWO, caught=True)
check("and so is a blank one, which git would otherwise read as its own kind of failure", code, 2)
check(
    "and it is this refusal rather than git's, which reads as a broken repo",
    "needs a ref" in printed,
    True,
)
code, printed = run_main(["--since", "main", "hookio"], tables=TWO, caught=True)
check("and naming modules as well is an error rather than one of them winning", code, 2)
check("and says which arguments made it ambiguous", "hookio" in printed, True)


# Through the seam, because the answers have to be fixed for the checks below to mean anything: the
# real history differs by branch, and inside the baseline copy there is no `.git` at all.
class FakeGit:
    """Canned `git` answers, and a record of what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        code, out, err = self.answers.pop(0)
        return subprocess.CompletedProcess(args, code, out, err)


fake = FakeGit((0, "base123\n", ""), (0, "plugin/lib/store.py\n\nREADME.md\n", ""))
check(
    "the changed files are the diff's lines, blank ones dropped",
    mutate.changed_since("main", fake),
    (["plugin/lib/store.py", "README.md"], None),
)
# The merge base, not the ref itself, and asserted off what git was asked rather than off the
# answer. A branch behind `main` shares no tip with it, so diffing the ref directly reports every
# file somebody else changed as this change's own, and the sweep would then run every table on a
# one-line PR.
check(
    "and the diff is taken against the merge base",
    fake.calls[1],
    ("diff", "--name-only", "base123"),
)

# The second guard, which no real input can reach: a base git cannot resolve fails at `merge-base`
# first. Deleting it was green before this seam existed, and what it protects is the case where a
# merge base comes back that `git diff` then refuses - a clean exit status read as nothing to sweep.
refused = FakeGit((0, "base123\n", ""), (128, "", "fatal: bad"))
paths, problem = mutate.changed_since("main", refused)
check("a diff git refuses is a reason too, not an empty list", paths, None)
check("and says it was the diff that failed", "cannot diff against" in (problem or ""), True)

# And the real git call, on the one input whose answer does not depend on this repo's history - so
# it holds inside the baseline copy too, where `.git` is not copied and every git command fails.
paths, problem = mutate.changed_since("definitely-not-a-ref")
check("an unresolvable ref comes back as a reason from git itself", paths, None)
check("and the reason names the ref", "definitely-not-a-ref" in (problem or ""), True)
# Which of the two guards answered, not just that one did, and this is the check that found the hole
# rather than a refinement of it. Deleting the merge-base guard entirely left the two above green:
# the empty ref it then passes to `git diff` fails there instead, so a reason still came back,
# naming the same ref, from the wrong step. The failure the deleted guard exists for is a merge base
# that comes back empty for a reason `git diff` happens to survive, and then the sweep reads a clean
# exit as nothing to sweep. Two answers that agree cannot say which one was read, one function in.
check(
    "and says which step could not answer, not merely that one could not",
    problem.split(" for ")[0],
    "no merge base",
)

print("and the exit code reaches the process, which is all CI can see")

# One step out from `main`'s return value again, and this one turns the whole gate off: dropping
# the `raise` from `raise SystemExit(main(...))` makes the sweep print its survivors and exit 0,
# with the suite green and `ci` green with it. Run as a real process, because the contract is the
# status, and with a module name that does not exist, which returns before `baseline` and so costs
# milliseconds rather than a suite run.
#
# `outside_sweep` matters here rather than being tidiness. This file runs inside the baseline copy
# and inherits the sweep marker, and the first re-entrancy guard turned this check red
# the moment it shipped: `mutate.py` refused, so exit 2 arrived for the wrong reason and the message
# was the refusal rather than `no table for`. `baseline` caught it, which is the line it exists for.
# A check that asserts what happens outside a sweep has to say so rather than inherit an answer.
done = subprocess.run(
    [sys.executable, str(HERE / "mutate.py"), "nosuchmodule"],
    capture_output=True,
    text=True,
    timeout=60,
    env=outside_sweep(),
)
check("a refusal is an exit status, not just a printed line", done.returncode, 2)
check("and the line is printed too", "no table for: nosuchmodule" in done.stdout, True)

print("and the copy it sweeps in is laid out the way the scoring assumes")

# `prepare` exists so this is assertable. Deleting its `unlink` left the suite green, the sweep
# clean and all sixteen caught, while making `verdict`'s "the suite passed" branch unreachable for
# every mutation the sweep runs, because the file removed here fails by construction in a mutated
# copy. The fourth instance of this file's own defect, in the line whose comment names the third.
with tempfile.TemporaryDirectory() as tmp:
    plain = pathlib.Path(tmp) / "plain"
    mutate.prepare(plain)
    check(
        "an unmutated copy keeps the table check, which is where it means something",
        (plain / "plugin" / "tests" / "test_mutations.py").is_file(),
        True,
    )

    swept = pathlib.Path(tmp) / "swept"
    # A mutation naming `store`, deliberately not `hookio`. Checked against `hookio.py` it read as
    # an assertion and was not one: `prepare` could hardcode the filename and this would still pass,
    # which is the argv-agrees-with-the-payload defect this module's history is about, reproduced in
    # a fixture. Two inputs that agree cannot say which one was read.
    elsewhere = ONE._replace(module="store", caught_by="test_store_claims.py")
    mutate.prepare(swept, elsewhere, "# mutated\n")
    check(
        "a mutated copy does not, since it would fail there whatever the mutation did",
        (swept / "plugin" / "tests" / "test_mutations.py").is_file(),
        False,
    )
    # The first line only. Comparing the whole file prints a ninety-line module into the failure
    # output when this goes wrong, and a check nobody can read the failure of gets skipped over.
    check(
        "and the module the mutation names is the one that got patched",
        (swept / "plugin" / "lib" / "store.py").read_text().splitlines()[:1],
        ["# mutated"],
    )
    untouched = (swept / "plugin" / "lib" / "hookio.py").read_text()
    check(
        "and no other module was touched", untouched == (mutate.LIB / "hookio.py").read_text(), True
    )
    check(
        "with the rest of the repo present, since the suite reads above plugin/",
        (swept / ".claude-plugin" / "marketplace.json").is_file(),
        True,
    )

print("and the runner underneath both gates can report a failure at all")

# `run.py` is in neither `TABLES` nor `UNSWEPT`, because the accounting at the top of this file is
# scoped to `plugin/lib` and the runner is not a module - so nothing asserted the one file whose
# silence turns both gates green at once. Probed: `if False and subprocess.run(...)` leaves it
# printing ten `===` headers and "everything passed" with every rule in the repo broken, and the
# sweep goes red with every mutation alive, which is the wrong reason and reads as wholesale drift.
#
# Two claims, and the second is easy to miss: `catchers` reads `FAILED: a, b` out of this output
# with a regex living in another file. The runner's summary line is a contract between the halves of
# the harness, and reformatting it costs the sweep every catch.
#
# Against a copy holding synthetic files rather than against the real suite, because the real one
# costs two seconds a call and because "everything passed" needs a file that passes by construction.


def runner(*files, select=()):
    """`run.py` over the given `(name, source)` files alone. Returns `(returncode, output)`.

    `select` is what the sweep passes for one mutation (#43), and it goes on the command line here
    for the same reason the rest of this fixture exists: a selection has to be probed against a
    directory the check controls. Pointed at the real suite it cannot be - a `run.py` that ignores
    its arguments then runs `test_mutations.py`, which reaches this line again, and the recursion is
    the one recorded two sections below at 4913 scratch repos in a minute. Here the copy holds two
    synthetic files and nothing that can call back into anything.

    Output is stdout and stderr together, which is new and which the refusal needs: `SystemExit`
    with a string writes to stderr, so a check reading stdout alone cannot tell a refusal from a
    silent empty run. Every other caller here is unaffected, both fixtures being quiet on stderr.
    """
    with tempfile.TemporaryDirectory() as tmp:
        here = pathlib.Path(tmp)
        (here / "run.py").write_text(
            (HERE / "run.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        for name, source in files:
            (here / name).write_text(source, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(here / "run.py"), *select],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return done.returncode, done.stdout + done.stderr


def before(out, first, second):
    """Whether `first` comes ahead of `second` in `out`, or which of them is missing.

    Not `out.index(first) < out.index(second)`, which raises when a substring has gone - and the
    regression this is for is exactly a line going missing. Deleting the header outright killed this
    file at its last line, so it lost its own `N failure(s)` summary and printed a traceback
    instead, which is the shape `read_by` and `injected` in the hook tests exist to prevent.

    Nothing asserts this function itself, which was asked and is the right answer: inverting the
    comparison is caught by the ordinary passing run, because the correct order is a definite one.
    Replacing it with `return True` goes unnoticed only alongside a second edit to `run.py`, and the
    sweep applies one at a time. Same standing as `check` above - at some point the assertions are
    the floor rather than the subject.
    """
    for text in (first, second):
        if text not in out:
            return f"{text!r} is not in the output at all"
    return out.index(first) < out.index(second)


# Not the word "fine", which is a substring of the header line that labels this file, so a check
# looking for where its output starts would find the header instead and compare a line to itself.
PASSING_SAYS = "the passing file ran"
PASSES = ("test_fine.py", f"print({PASSING_SAYS!r})\n")
FAILS = ("test_broken.py", "raise SystemExit(1)\n")

code, out = runner(PASSES)
check("a directory where every file passes is an exit 0", code, 0)
check("and says so, since that line is what a reader looks for", "everything passed" in out, True)
check(
    "and names no catcher, which is what an unasserted rule looks like", mutate.catchers(out), None
)

code, out = runner(PASSES, FAILS)
check("one failing file out of two is a non-zero exit", code, 1)
check(
    "and its FAILED line names that file, in the shape the sweep's regex reads",
    mutate.catchers(out),
    ["test_broken.py"],
)
# Every file, whatever it did, and each header ahead of the output it labels. Nothing parses these,
# but the synthetic fixtures throughout this file open with a `=== test_hook.py` line, so it is a
# shape they assert the scoring understands while nothing asserted the runner prints it. Deleting
# the header left this file green before this check - and the first version of the check compared a
# list of header lines, which says nothing about "before": moving the print to after the subprocess
# left it green too, with every header labelling the file above it.
#
# `run.py` sorts the glob so its output is reproducible. Nothing here asserts that, deliberately.
# The alternative to sorting is filesystem order, which is not a fixed answer to write a check
# against: here it happens to be creation order, so an assertion on it would pass on this machine
# whether the sort is there or not.
check(
    "and each file is announced, pass or fail",
    sorted(line for line in out.splitlines() if line.startswith("=== ")),
    ["=== test_broken.py", "=== test_fine.py"],
)
check(
    "and announced before it runs, rather than labelling the file above it",
    before(out, "=== test_fine.py", PASSING_SAYS),
    True,
)

print("and it runs the one file the sweep asked for, or says why it cannot")

# The runner's half of #43. `sweep_one` passing `only` is asserted through its own seam above, and
# this is the other end of it: a `run.py` that takes the name and then runs everything anyway leaves
# every verdict in the sweep exactly as it is while costing what it cost before, which is a change
# that reports its own success and delivers nothing.
code, out = runner(PASSES, FAILS, select=["test_fine.py"])
check(
    "a name it has runs that file, and the failing one beside it never runs",
    (code, sorted(line for line in out.splitlines() if line.startswith("=== "))),
    (0, ["=== test_fine.py"]),
)
# And the refusal, which is the one place here where an empty result is worse than an error: a run
# of no files exits 0 and prints "everything passed", which `verdict` reads as "the suite passed, so
# nothing asserts this rule". One typo in a `caught_by` field would report every mutation in that
# table as unasserted and read exactly like a finding.
#
# Three parts, and the traceback one is the reason it is not two. Deleting the refusal leaves the
# lookup on the next line to raise `KeyError`, which is also non-zero and also prints the name, so
# "non-zero, and the name appears" was green with the refusal gone - a check satisfied by a crash,
# which is the class this file exists to find.
code, out = runner(PASSES, select=["test_typo.py"])
check(
    "and a name it does not have is a refusal naming it, not a crash that mentions it",
    (code, "test_typo.py" in out, "Traceback" in out, "everything passed" in out),
    (1, True, False, False),
)

print("and a sweep refuses to start inside a sweep")


# 204 orphaned processes, half a core, two hours, and `ps` the only trace. See `mutate.SWEEPING`.
#
# In-process with both slow calls stubbed to raise, and emphatically not as a real `mutate.py store`
# with the marker set, which is what this was first written as. That version is the thing it checks:
# delete the guard and it spawns a sweep, whose baseline copy runs this file, which spawns a sweep,
# and `timeout=` kills the direct child only. Measured on a copy with the refusal removed - 124 live
# processes and 4913 orphaned scratch repos, 2.9 GB, inside a minute - so the single most likely
# edit to this file, editing the guard, reproduced the incident the guard is for. It also could not
# report: the timeout escaped at module level, so the file died with a traceback instead of naming a
# check, and the companion check below it never ran at all.
#
# The stubs are what make the "before baseline" half assertable, and they cannot spawn anything. A
# module that has a table, deliberately not `nosuchmodule`: with an unknown name `main` exits 2 from
# the no-table refusal instead, so this would pass with the guard deleted. That is the
# argv-agrees-with-the-payload defect this repo keeps rediscovering, so the name is real, the only
# thing here that can produce exit 2 is the guard, and the message is checked too, not the status
# alone.
def from_inside_a_sweep(argv, value="1"):
    """`main` with the marker set and both slow calls booby-trapped, never a nested process."""
    real = (mutate.baseline, mutate.sweep_one)
    marker = os.environ.get(mutate.SWEEPING)

    def die(*args, **kwargs):
        raise AssertionError("reached past the refusal")

    mutate.baseline = die
    mutate.sweep_one = die
    os.environ[mutate.SWEEPING] = value
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            return mutate.main(argv), printed.getvalue()
    except AssertionError as exc:
        return f"it {exc}", printed.getvalue()
    finally:
        mutate.baseline, mutate.sweep_one = real
        if marker is None:
            del os.environ[mutate.SWEEPING]
        else:
            os.environ[mutate.SWEEPING] = marker


code, printed = from_inside_a_sweep(["store"])
check("a sweep reached from inside a sweep refuses", code, 2)
check(
    "and names the variable that told it so, which the caller did not set on purpose",
    mutate.SWEEPING in printed,
    True,
)
# Ahead of `baseline`, or the refusal costs a suite run per level and the chain is merely slower.
check("and refuses before spending a baseline run", "=== baseline" in printed, False)
# Whitespace means unset, as it does for the only other CC_EXCHANGE_* variable one file over. Also
# the one check here that proves the stubs are reached when the refusal does not fire, so the three
# above are asserting the guard rather than a `main` that cannot get anywhere at all.
blank, _ = from_inside_a_sweep(["store"], "   ")
check(
    "and a blank marker is not a marker, matching exchange_root",
    blank,
    "it reached past the refusal",
)

# The other side of the seam. `main` refusing is half of it; the half that makes the refusal
# reachable is `run_suite` putting the marker in the child's environment, and a guard nothing sets
# never fires. Through `ran`, which already records what the stub was called with and absorbs a stub
# that raises instead of letting it escape at module level and take the rest of the file with it.
#
# The marker is popped around the call rather than left as it is. Inside the baseline copy it is
# set, so `env={**os.environ}` with the marker no longer added would satisfy this - two inputs that
# agree cannot say which one was read. Reducing `run_suite` to exactly that left this green in the
# `mutate` job and red only standalone, which is the worse half of the two to be green in.
marker = os.environ.pop(mutate.SWEEPING, None)
try:
    ran(Finished(0, "", ""))
finally:
    if marker is not None:
        os.environ[mutate.SWEEPING] = marker

check(
    "and the suite a sweep spawns is told that it is inside one",
    ran.kwargs.get("env", {}).get(mutate.SWEEPING),
    "1",
)
# `env=` replaces the child's environment rather than adding to it, so a marker passed alone would
# leave the suite without PATH or the interpreter's own variables. Green either way on this machine
# until it is not, which is the kind of check worth having.
check(
    "with the rest of the environment intact, since env= replaces rather than adds",
    "PATH" in ran.kwargs.get("env", {}),
    True,
)

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
