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
3.11 and 3.13 on Linux and the newer two on macOS.

Lint and the shell handlers, matching what CI runs:

```sh
uvx ruff@0.16.9 check .
uvx ruff@0.16.9 format --check .
shellcheck plugin/hooks-handlers/*.sh
```

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

`ci` is the aggregate job at the bottom of the workflow, and it is the only check the ruleset names.
That is deliberate: naming the matrix legs individually would put every OS and Python version into a
repo setting, so dropping one would block `main` forever on a check that can never report again. Add a
job to the workflow and add it to `ci`'s `needs`, or it gates nothing.

**A new job is not free, and the unit is not the second.** Actions bills per job, rounded up to a
whole minute, and macOS bills that minute at 10x. Eleven jobs finishing in twenty-eight seconds of
wall time cost twenty-nine minutes, two thirds of it on the two macOS legs. So a check that needs no
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
