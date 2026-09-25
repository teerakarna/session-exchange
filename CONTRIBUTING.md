# Contributing

## The one rule that is load-bearing

**A check has to be able to fail.**

Every gate gets broken deliberately once, and what the failure looks like gets written down. A test
that passes identically whether the behaviour exists or not is asserting nothing, and it looks
exactly like a test that passes.

This is not a stylistic preference. This project exists because a hand-rolled version of it matched
zero handoffs for ten days and reported a quiet week, on a machine where nothing was wrong with the
machine. The silence was indistinguishable from success. So a PR here is expected to say which gate
it broke and what the failure output was, and a new check with no recorded failure mode is treated as
untested.

Worked examples of the discipline, all of them real: the legacy-hook warning made unconditional (it
satisfies every positive assertion and turns the injected section into something a reader learns to
skip); a schema grown a keyword the validator does not implement; a `hooks.json` handler path
resolving to nothing; `safe_id` made permissive.

Two more came out of the ledger parser, and both were *deletions*, which is the outcome worth
expecting. Breaking each of its rules in turn found one that no mutation could fail - a guard
excluding the continuation marker, duplicating work the entry anchor already did - and one whose
clever branch no arrangement of the input could reach, an escape-aware emphasis stripper written for a
case that cannot occur. An untestable rule is not free: it reads as protection, so the next person
keeps it and widens the thing that was actually holding the line.

The importer's key produced the other two outcomes. One was a missing gate rather than a dead rule:
stop comparing status and every check still passed, because nothing asserted that closing an entry in
the ledger after it was imported reaches the stored row. That is the ordinary case, and it was absent
from a suite that read as thorough. The other was in the sweep itself. A mutation whose text no longer
matched the file was scored as "no failure", so the tool built to find checks that cannot fail had the
same defect, and it was reporting a real rule as untested while hiding a fake one. If you mutate by
string replacement, assert the replacement happened.

The sweep has since been pointed at a module nobody had asked about, and found the worst instance
yet: `hookio.event_name` could be cut down to `return default`, ignoring the payload entirely, and
the whole suite stayed green. That is the specific defect the module's own docstring says made one
lane's handoffs invisible, and it was reintroducible without a single failing test, because every
case in `test_hook.py` happened to pass the same event name in argv and in the payload. Agreement
between two inputs is not a test of which one is read.

The lesson generalises past this repo: **a sweep is only worth what it has been pointed at.** Six
rules in a seventy-line module, five of them unasserted, in a suite that reads as thorough because
the modules that got swept are thorough. Point it at the ones that did not.

The sweep itself now lives in `plugin/tests/mutate.py` rather than being rewritten in `/tmp` each
time, which it was, four times, losing its tables and its own bug fixes with every session. The
tables are the durable part; the runner is incidental:

```sh
python3 plugin/tests/mutate.py            # every module with a table
python3 plugin/tests/mutate.py hookio     # one module, while writing its table
```

A sweep costs one full suite run per mutation, so it is its own CI job and not part of
`plugin/tests/run.py`. What *is* in the suite is `test_mutations.py`, the cheap half: it asserts that
every mutation still matches the source it claims to patch, and that `TABLES` and `UNSWEPT` together
account for every module in `plugin/lib`. Both failures are otherwise silent. A mutation whose text
has drifted tests nothing while still reporting a catch, and none of the eleven modules had a table in
the repo at all before this, which is the same "thorough where it was pointed" problem one level up.
Three have one now and `UNSWEPT` names the eight that are owed.

Writing it down cost two more instances of the defect, in the harness, both found by probing it
rather than by reading it. The scratch copy was `plugin/` alone while `test_plugin_layout.py` reads
the manifest above it, so the suite failed on every run, every mutation scored as caught, and a
survivor was undetectable - hence `baseline`, which requires the unmutated copy to pass before any
result counts. Then `test_mutations.py`, running inside the swept copy, failed by construction on
every table mutation, since a mutation is exactly an edit that stops a table entry matching. Both
are a gate that cannot fail, which is what the tool is for. **Assert the ground you are standing on**
belongs next to "assert the replacement happened", and the first honest run found three live rules in
`hookio`, a module already recorded as swept.

Review pass after review pass on that diff kept finding the same thing in the harness, most of it
introduced by the previous pass's own fix, which is why a review here runs until a pass comes back
clean rather than a set number of times. Pulling the scoring out into functions that can be fed
synthetic output made it assertable and it got asserted - and left the return value it feeds
unasserted, then the two-line functions that call it, then the `unlink` that keeps the survivor branch
reachable at all, then the count in the summary line, which was read off the table rather than off
work done, so sweeping 3 of 16 mutations still printed "every one of 16 mutation(s) was caught". Then
the process status: drop the `raise` from `raise SystemExit(main(...))` and the sweep prints its
survivors and exits 0, which turns the whole gate off with the suite green. Then the printed summary
itself, and `run_suite`, the one side of the seam the stubs had replaced everywhere, where combining
stderr into the output and reporting a hang instead of propagating it were both free to delete. Then
the argument crossing that seam: a stub with a defaulted parameter answers `run_suite()` and
`run_suite(mutation)` alike, so nothing objected to `sweep_one` asking for a copy it had not patched.
**A seam you introduce to make something assertable needs the wiring on both sides of it asserted
too**, or the half that is easy to test is the only half that is tested.

Last in that chain was the file underneath all of it. `run.py` is what both gates read - the suite's
exit status, and the `FAILED:` line the sweep scores every mutation off - and it was in neither
`TABLES` nor `UNSWEPT`, because the accounting is scoped to `plugin/lib` and a runner is not a module.
Stop it noticing a failing file and the suite prints "everything passed" with every rule in the repo
broken, while the sweep goes red with every mutation alive, which names the wrong problem. It has its
own checks now, against a copy of it holding two synthetic files, one passing and one failing, and
they cover the shape of that summary line as well as the exit status: `catchers` reads it with a regex
living in another file, so it is a contract between the two halves of the harness rather than a print.

The same passes found six more live rules in `hookio`, nine in total, in a module of seventy lines -
most of what this diff adds to it is comments about why. The worst was two characters:
`json.loads(...)` on a payload of `5` returns an int, every `.get` on it raises from outside the one
try block `hook.main` has, and the hook exits 1 with a traceback - the single thing this plugin
promises never to do, with the whole suite green.

That one is also the cleanest example of the other half of the discipline. The first fix was `or {}`
and the first check fed it `null`, which is the one case `or {}` happens to handle, so the check was
green while `5`, `true`, `"x"` and `[1]` still exited 1. **A fix is only as wide as the input that
showed the bug**, and a check that feeds back exactly that input reads as cover for the rest of the
rule. One example per branch of a guard is a test of the example.

The guard two lines below it is the same lesson told three times, and the third telling is why it no
longer names a type at all. `except (ValueError, OSError)` around the read grew `AttributeError` when
`sys.stdin` turned out to be `None` whenever fd 0 is not open; the pass after that found a stream
whose `read` answers `None`, which is a `TypeError`, and a deeply nested array, which is a
`RecursionError` and so not even in the family. Three passes, three types, each one added as wide as
the input that had just been tried. It is `except Exception` now, because the list was never the rule:
`payload` is called outside `main`'s only try block, so **at a boundary whose contract is "never
raise", enumerating what may go wrong is a guess, and each guess reads like a decision**. The
`isatty` guard above it keeps its list, because both of its arms have an input that shows them.

The helper those checks are written through had the same list, which is worth its own line. `read_by`
exists so an escaping exception prints one FAIL naming itself instead of a traceback that takes the
rest of the file down - and it was catching precisely what the guard under test caught, so the first
input that escaped the guard escaped the helper too and the file died at that line. The sweep still
scored a catch, off the crash rather than off the assertion. **A helper that shields the checks from
the code under test must not share the code's own idea of what can go wrong.**

The pass after that found the same shape in a check written during the pass that wrote the rule down,
which is worth knowing about the rule: `out.index(a) < out.index(b)` raises when a substring has gone,
and a line going missing is exactly the regression it was asserting. So the general form is wider than
helpers. **A check whose subject can be absent has to say so, not evaluate an expression that needs it
to be there** - otherwise the one failure it exists for is the one it cannot report.

## The corollary, which cost more to learn

**Run the thing.** The two worst bugs in the first working version passed the whole suite: `claim`
took its display name from the calling session rather than the session being claimed for, so it wrote
someone else's claim under the caller's name and then reported it back as stale; and the `SessionStart`
handler read a payload field that does not exist. A green suite is not a demonstration. Use the
commands, read the output, and check it says something true.

Running it over the real fixture is what found the importer's key was not idempotent. The key holds a
64-character prefix of the headline, and on two of the ten entries the cut landed on a space. Writing
trimmed nothing, reading normalised the stored value and took the space off, so the key came back a
character short, the row stopped matching the source it was written from, and the entry re-imported as
new while the original reported as an orphan. Reasoning about the rule would not have turned that up.
Ten failing checks on the first run did.

## Running it

```sh
python3 plugin/tests/run.py
```

No install step, no virtualenv, no dependencies. That is a hard constraint rather than a convenience:
the hooks invoke whatever `python3` is on PATH with no opportunity to install anything, so a
third-party import is not a dependency decision, it is an `ImportError` at session start on every
machine but yours. CI fails the build on one.

The same reasoning sets the floor at **Python 3.9**, which is what a stock macOS ships. CI runs 3.9,
3.11 and 3.13 on Linux, and 3.13 on macOS. One macOS leg rather than two: the platform-sensitive parts
are `os.kill` and `ps`, which do not vary by interpreter version, and macOS minutes bill at 10x.

Lint and the shell handlers, matching what CI runs:

```sh
uvx ruff@0.16.9 check .
uvx ruff@0.16.9 format --check .
shellcheck plugin/hooks-handlers/*.sh
```

None of that reads a check and asks whether it could fail, which is the one thing this repo cares most
about, so a review of the diff is expected before a PR as well. `CLAUDE.md` states how to size it and
what to point it at, and states it only there: a rule written out in two files is the drift this project
is about.

## The schemas are the contract

State is validated against `plugin/schemas/` on the way to disk. If a field needs adding, it goes in
the schema, not into a hand-written check in Python: duplicating the contract in two places is the
drift class this whole project is about.

The validator covers only the subset of JSON Schema those files use and **raises** on any keyword it
does not implement, with a test walking the schemas to assert every keyword in use is covered. That
property is the only thing that makes hand-rolling one defensible rather than reckless, because the
failure mode of a partial validator is a constraint that quietly does not run. If you add a keyword,
implement it and the meta-test will tell you when you have not.

## Things that are deliberate, so read before removing

- **Nothing names a path.** The plugin is code and wiring; the environment root is state and config.
  That split is the portability, and a hardcoded path anywhere in here is the bug class being removed.
- **Roots never read each other**, in either direction. This is the test that must never regress.
- **One file per writer**, never a shared append target. Concurrent sessions on one file contend, and
  it is also why no write needs a lock: the only writer of a session's claim is that session.
- **A hook must never fail a session start.** Everything is wrapped, exits 0, and reports the problem
  in the injected context instead. A bad root resolves to no root and says why.
- **Silence is a real answer.** No root means no output and no files, ever. An empty section injected
  every session trains the reader to skip the section.
- **Legacy detection is by shape, never by literal name.** Two of the scripts being replaced carry one
  environment's project prefix, which must not ship in a generalised tool; a glob also survives a
  rename.

## Commits and PRs

Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`). Branch and PR for everything; nothing lands
on `main` directly. No `Co-Authored-By` trailers.

That last part is enforced rather than trusted: a ruleset on `main` requires a pull request and a green
`ci`, blocks force pushes and branch deletion, and has no bypass actors, so a direct push is rejected
for the owner too. Zero approvals are required, because an approval only the author could give is one
that gets bypassed, and a gate routinely bypassed teaches that gates are optional.

`mutate` is the one job kept out of `checks` without a permissions reason for it, against the
arithmetic below: it runs the suite once per mutation, and its failure names a rule nothing asserts
rather than a rule broken, which is not what "checks failed" would say. That costs one Linux minute
per run, because `checks` takes thirty seconds and folding a minute of sweep into it stays inside two
billed minutes while splitting them bills three. The price is named in the job's own comment rather
than argued away, which is what the first version of it did.

`ci` is the aggregate job at the bottom of the workflow, and it is the only check the ruleset names.
That is deliberate: naming the matrix legs individually would put every OS and Python version into a
repo setting, so dropping one would block `main` forever on a check that can never report again. Add a
job to the workflow and add it to `ci`'s `needs`, or it gates nothing.

**A new job is not free, and the unit is not the second.** Actions bills per job, rounded up to a
whole minute, and macOS bills that minute at 10x. The eleven jobs this workflow had before it was
consolidated finished in twenty-eight seconds of wall time and cost twenty-nine minutes, two thirds of
it on the two macOS legs it had then. So a check that needs no
special runner, no extra permission and no independent report belongs as a step in `checks`, not as a
job of its own - four of them were four separate jobs, six to eighteen seconds each, billing four
minutes to do half a minute of work. `secrets` is the counter-example worth copying: it stays its own
job because it needs `pull-requests: write`, and spreading that permission across the steps that run
an unpinned `npm install -g` to save a minute is the wrong trade.

Two things follow from the same arithmetic. Every job carries `timeout-minutes`, because the default
cap is 360 and a hang on a macOS leg is an hour of billing per wasted hour. And the `concurrency`
block cancels a superseded run on a PR branch, but never on `main`, where each push is a merge whose
result has to stay individually visible - which is why the group key falls back to `github.run_id`
off a PR rather than the ref: a queued run is dropped when another joins its group, regardless of
`cancel-in-progress`.

Keep a PR readable in one sitting. The first one here was 21 files and 2249 lines, which got through
only because it was all new code with no existing behaviour to regress. That is a property of a
skeleton, not of the work after it.

Plain `-` rather than an em dash or an en dash, in code comments and prose alike.
