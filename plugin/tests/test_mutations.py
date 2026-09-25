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
and three do now, which is exactly how the suite came to read as thorough: the modules that got
swept are thorough. So `TABLES` and `UNSWEPT` together have to account for every module in
`plugin/lib`, and a new module joins neither by accident.

`UNSWEPT` is deliberately a list of names rather than a count or a flag. A count drifts without
saying what changed, and a flag lets a module be quietly forgotten.
"""

import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mutate  # noqa: E402

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


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
CAUGHT = "=== test_hook.py\nFAILED: test_hook.py\n"

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

print("and each of those verdicts is what the sweep actually asks for")


# Found the same way as everything else here, by breaking it: replacing `baseline`'s body with
# `return None` left the whole suite green, and a baseline that never refuses is the exact defect
# `baseline` was added to fix, scoring every mutation as caught. The scoring got asserted above and
# the two-line functions that call it did not, which is the seam problem one step further out.
def through(result, call):
    """Run `call` with `run_suite` stubbed, since these two functions are only wiring.

    `through.handed` is what the stub was given, and it is recorded because a stub with a defaulted
    parameter answers `run_suite()` and `run_suite(mutation)` alike, so the return value alone says
    nothing about which call the wiring makes. Dropping the argument in `sweep_one` sweeps an
    unpatched copy for every entry, which the baseline has just proved passes, so every one of them
    comes back as "the suite passed, so nothing asserts this rule". Red, but naming the whole table
    as unasserted when the defect is one argument.
    """
    real = mutate.run_suite
    through.handed = "it was not called at all"

    def stub(mutation=None):
        through.handed = mutation
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
check("having asked for no mutation, which is the whole point of it", through.handed, None)
check(
    "sweep_one asks verdict, and reports the mutation it was given",
    through((1, "FAILED: test_store_claims.py\n"), lambda: mutate.sweep_one(once)),
    (False, "caught by test_store_claims.py rather than test_hook.py"),
)
check("and asked for that mutation rather than for a clean run", through.handed, once)

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


def ran(outcome, mutation=None):
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

    def stub(args, **kwargs):
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
        return mutate.run_suite(mutation)
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


def run_main(argv, *, tables, caught, baseline_problem=None):
    """`main`'s exit code and what it printed, with the two slow calls stubbed."""
    real = (mutate.TABLES, mutate.baseline, mutate.sweep_one)
    mutate.TABLES = tables
    mutate.baseline = lambda: baseline_problem
    mutate.sweep_one = lambda mutation: (caught, "stubbed")
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            return mutate.main(argv), printed.getvalue()
    finally:
        mutate.TABLES, mutate.baseline, mutate.sweep_one = real


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

# Reachable without anyone meaning it: move the tables into `UNSWEPT` and the accounting above still
# balances, so a sweep that swept nothing would report "every one of 0 mutation(s) was caught".
code, printed = run_main([], tables={}, caught=True)
check("sweeping nothing is not a pass", code, 1)
check("and says so rather than reporting zero of zero", "proves nothing" in printed, True)

code, printed = run_main(["nosuchmodule"], tables=TWO, caught=True)
check("and a module with no table is an error, not an empty success", code, 2)
check("and names the module it has nothing for", "nosuchmodule" in printed, True)

print("and the exit code reaches the process, which is all CI can see")

# One step out from `main`'s return value again, and this one turns the whole gate off: dropping
# the `raise` from `raise SystemExit(main(...))` makes the sweep print its survivors and exit 0,
# with the suite green and `ci` green with it. Run as a real process, because the contract is the
# status, and with a module name that does not exist, which returns before `baseline` and so costs
# milliseconds rather than a suite run.
done = subprocess.run(
    [sys.executable, str(HERE / "mutate.py"), "nosuchmodule"],
    capture_output=True,
    text=True,
    timeout=60,
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


def runner(*files):
    """`run.py` over the given `(name, source)` files alone. Returns `(returncode, stdout)`."""
    with tempfile.TemporaryDirectory() as tmp:
        here = pathlib.Path(tmp)
        (here / "run.py").write_text(
            (HERE / "run.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        for name, source in files:
            (here / name).write_text(source, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(here / "run.py")], capture_output=True, text=True, timeout=60
        )
        return done.returncode, done.stdout


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

print()
if failures:
    print(f"{len(failures)} failure(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
