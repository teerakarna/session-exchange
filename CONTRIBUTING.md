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
tables are the durable part; the runner is incidental, and the tables are one file per module under
`plugin/tests/tables/` for a reason worth reading in that package's docstring: the path is what tells
the narrowing which module a new mutation belongs to, so adding one costs a single module's sweep
instead of all nine.

```sh
python3 plugin/tests/mutate.py                      # every module with a table
python3 plugin/tests/mutate.py hookio               # one module, while writing its table
python3 plugin/tests/mutate.py --since origin/main  # only what this change could have broken
```

A sweep costs one full suite run per mutation, so it is its own CI job and not part of
`plugin/tests/run.py`. What *is* in the suite is `test_mutations.py`, the cheap half: it asserts that
every mutation still matches the source it claims to patch, and that `TABLES` and `UNSWEPT` together
account for every module in `plugin/lib`. Both failures are otherwise silent. A mutation whose text
has drifted tests nothing while still reporting a catch, and none of the eleven modules had a table in
the repo at all before this, which is the same "thorough where it was pointed" problem one level up.
Nine have one now. `ledger` and `reconcile` are in `NOT_YET`, tables owed, and `cli` is the single
entry in `DECLINED`: 400-odd lines of argument parsing and output formatting, every path of it reached
by somebody who typed the command and is reading the answer, with `test_cli.py` driving all of it end
to end. That is the trade the sweep loses on, and it is a claim about `cli` rather than a general
argument - it was briefly recycled for the other two, and once written out honestly it did not apply
to them, because neither has a caller at all so there is no person and no answer to misread (#40).

The split exists because a debt list that quietly contains permanent entries stops being read as a
debt list. Reversing either decision is an edit to a dict, which is the point of writing the reason
down rather than the decision. Both stay even when empty, because a new module in `plugin/lib` fails
the accounting until it gets one of the three - a table, a place in `NOT_YET`, or a recorded reason in
`DECLINED` - and that forced choice is the mechanism.

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
3.11 and 3.13 on Linux in one job, and 3.13 on macOS in another. One macOS run rather than two: the
platform-sensitive parts are `os.kill` and `ps`, which do not vary by interpreter version, and macOS
minutes bill at 10x.

That 10x is also why the macOS job runs on every push to `main` but on a pull request only once it is
out of draft. **Open PRs with `gh pr create --draft` and `gh pr ready` when they are done.** A draft
cannot be merged, so nothing reaches `main` without having been through macOS, and the six pushes it
takes to write a branch stop costing ten billed minutes each. Forgetting costs you nothing but the
minutes.

Lint and the shell handlers, matching what CI runs:

```sh
uvx ruff@0.16.9 check .
uvx ruff@0.16.9 format --check .
shellcheck plugin/hooks-handlers/*.sh
```

`ruff format` will not fix E501 in a comment or a docstring, because it does not rewrap prose, and
there is a lot of prose here. Rewrapping it by hand left a stub line ("pid," alone) in three
consecutive commits on #56 and the same stub survived into #59, so a script is the better idea - but
only if it can tell prose from code. One written for this reflowed a `check(...)` call as though the
arguments were a paragraph, which put a line break inside a string literal in two files and left them
unparseable. Whatever does the reflowing has to key on the run of lines sharing a `#` or being inside
a docstring, never on "this line is too long", and `python3 -c 'import ast; ast.parse(...)'` on every
file it touched is the cheap check that it did. A long string is split with implicit concatenation
instead, which `ruff format` then leaves alone.

## What runs when, and how to run it yourself

Every gate here has a local command, because Actions goes down, the free minutes run out, and a gate
you cannot run yourself is one you find out about after pushing. Nothing in CI is a step that only
exists inside CI.

| Tier | Command | In CI |
|---|---|---|
| Lint and shape | `uvx ruff@0.16.9 check .`, `ruff format --check .`, `shellcheck plugin/hooks-handlers/*.sh`, `claude plugin validate --strict ./plugin` and `--strict .` | `checks`, every push |
| The suite | `python3 plugin/tests/run.py` | `test`, every push, on 3.9/3.11/3.13 |
| The suite on macOS | `python3 plugin/tests/run.py` | `test-macos`, on `main` and on PRs out of draft |
| Sweep, narrowed | `python3 plugin/tests/mutate.py --since origin/main` | `mutate`, every push to a PR |
| Sweep, full | `python3 plugin/tests/mutate.py` | `Sweep` workflow, weekly on `main` and on demand |
| Secrets | none, unless you have `gitleaks` installed | `secrets`, every push, full history |

To check one new rule without paying for a whole sweep, go through `mutate.run_suite(mutation)`, which
copies the repo to a fresh temp directory per mutation. Do not patch a file in `plugin/lib` in place,
run a test, and restore it. That reads like the same thing and is not: the mutated and restored files
have different sizes but successive *mutations* often have the same one, `.pyc` invalidation is
(mtime, size) with one-second mtime granularity, and two same-size mutations written inside one second
make Python reuse the bytecode compiled from the first. Verifying the seven mutations of #45/#46/#47
that way, two of them scored against the previous mutation's code and the failure named a check
neither of them touched. The sweep itself is not exposed to this - fresh directory per mutation, and
`__pycache__` is in `IGNORE` - but the shortcut around it is, and it fails by attributing a real
failure to the wrong rule, which is the direction that does not look like a bug.

`.pre-commit-config.yaml` wires lint, shellcheck and the suite to git, if you want them there.
Not the two `claude plugin validate` calls, which need `claude` on PATH, so run those by hand or
leave them to `checks`:

```sh
uvx pre-commit install --install-hooks   # lint and shape on commit, the suite on push
uvx pre-commit run --all-files           # or just run the commit tier now
uvx pre-commit uninstall                 # and out again
```

Optional on purpose, and `uvx` so that sending a patch does not mean installing anything: `ci` is the
authority on whether a change is good, and every hook in there runs a command from this file. What it
buys is the round trip, a format failure found in under a second rather than two minutes later in a
log. The sweep is in neither stage, for the arithmetic below.

Of the tiers held back from some pushes, the full sweep is the one held back purely by arithmetic
rather than taste. A sweep is one full suite run per mutation, and every figure here is labelled with the count it
was taken at, because a number that quietly re-labels itself as the tables grow is the whole problem:
six tables was 87 mutations and just over four minutes locally, eight was 144 and eight and a half, and
the ninth table was measured at 14m51s while it stood at 177 mutations. It is 191 now and sixteen and a
half. The ninth is why the figures are worth keeping: scaling the 144 at its own 3.5s per mutation
would have predicted ten and a half at 177, and it took fifteen.

Every figure in that paragraph is a laptop, and the runner is a different measurement rather than the
same one scaled. Three full resweeps of the same 191 over three consecutive commits came in at 20m44s,
17m08s and 14m15s - 6.5s, 5.4s and 4.5s per mutation, getting faster while the suite got longer. Two more
resweeps of the same count came in at 5.2s and 4.7s, inside those three, and then a resweep of 198 came
in at 4.1s, below all five. So the band is 4.1 to 6.5 seconds. The sentence here said the two inside ones
"fall inside those three rather than extending them", which was true when written and was falsified by the
next run: a claim about a range, phrased as though the range were now settled, is the shape to avoid. Say
what the samples are and let the band be whatever they say. A spread of more than half swallows every
local figure at every count, so a tighter reading of it is not supported. Naming one is the older mistake:
the comment in `ci.yml` carried "between four and a half and four and three quarters" for the
87-mutation set with no samples recorded beside it, so where that quarter-minute came from is not
answerable now, and four later resweeps put the runner spread at three to five minutes. The first
reading of the 191 figures repeated it a different way, off the runner's 6.5s against a 6.0s laptop
figure: half a second was called the machine and the rest the added checks, which is one sample per
cause and cannot separate them. The second runner resweep at 5.4s is what killed it. `timeout-minutes`
on the `ci` sweep is `sweep.yml`'s number by parity rather than anything derived from these, and what
they are for is the floor it has to clear: the slowest full resweep in the logs, never the latest one
and never a laptop. 15 minutes was chosen off a laptop, and the sweep it was sized for ran to 15m15s
and was canceled.

The cost is mutations times suite length, not mutations, so a new table pays twice - its own mutations,
and the checks it adds to the suite that every older table's mutations then run. Per-mutation cost went
from 3.5s at 144 to 5.0s at 177, was 5.2s at 191, 5.7s at 198 and is 7.1s at 207 on the same laptop. The
last step is the paragraph's own point arriving: nine mutations were added and the suite went from 1577
checks to 1649, so the per-mutation figure moved by more than the nine mutations cost on their own, and
the full sweep went from 1128s to 1475s. That is well past what a push should carry to
re-answer a question the last push answered about code it did not touch, and each table added makes it
worse than the one before. So `ci` sweeps only the modules the change could have affected, and the full
sweep runs weekly where the length of it does not matter. The run prints its own per-mutation figure
at the end now, so the next revision of this paragraph comes off a log line rather than off dividing a
job total by a count.

The narrowing spent its first months narrowing nothing, which is worth knowing before trusting it. The
tables lived in `mutate.py`, a change to `mutate.py` resweeps everything because it decides what every
verdict means, and the rule in this repo is that a fix adds a mutation - so nearly every push paid the
full sweep, and the narrow path applied only to a change that asserted nothing new about itself. Split
per module (#36), a new mutation is a diff in one path that names its own module.

It is still not a ceiling, and the workflow has to be written for that: a change to `run.py`, to
`mutate.py`, to `tables/shape.py` or `tables/__init__.py`, or to `test_cli.py` widens `--since` to
every table, so `ci`'s sweep job carries the same `timeout-minutes` as the weekly one rather than a
tighter number sized for the usual case.

That narrowing is in `mutate.py --since`, not in the workflow, so the command CI runs is the command
you run. It is wider than "the lib modules that changed", and the extra width is the part that
matters: a test file maps to the modules its checks catch, because a check deleted from a test file is
exactly how a mutation stops being caught and that diff touches nothing under `plugin/lib` at all. A
change to the harness itself resweeps everything, since it decides what the sweep measures, and so does
a change to `test_cli.py`, which is no mutation's `caught_by` and still catches mutations in most of
the lib because driving a command end to end goes through most of it (#27). A change that no sweep can
measure - a doc, a workflow, a handler - exits 0 saying so, which is deliberately not the same output
as the refusal for a sweep that ran and proved nothing.

Two things the narrowing gives up, both real. A rule can stop being asserted for a reason no diff
points at: a check that covered a second module by accident, an interpreter change under the suite,
two changes that are each fine and together are not. And a module in `UNSWEPT` is swept by nothing at
all, weekly included, which is why a change to one of those prints a line saying the change went
unswept rather than passing quietly. The weekly run is the net under the first; issue #55 is the second.

A third thing the scoring gives up, part of which is now reported. A mutation counts as caught when
the file named in its `caught_by` fails, and a file that dies on a traceback fails too - so a module
mutated into raising early scored as caught for every rule that file asserts, including all the ones
after the point where it stopped running. The sweep now checks that the named file printed a failing
check rather than only exiting non-zero, and tallies the ones that did not at the end (#42). Not an
exit code: being mutated into raising is a legitimate way to be caught, and a gate that fails on a
legitimate catch gets bypassed.

That catches "died having asserted nothing" and not "died". A file that fails one check and then
raises on the next line still reads as an ordinary catch, and the rules after the crash point are
still credited. Telling that apart needs the number of checks the file owed, and nothing has it, which
is #57.

Two other things are tiered, and both were sized off a measurement rather than an instinct (#73, which
has the billed-minute breakdown). The sweep does not run on a push to `main`, because after a squash
merge `--since` gives exactly the diff the PR already swept - the interaction case, where `main` moved
under the branch, is the weekly full sweep's job and it covers every table rather than a narrowed set.
And the macOS job runs on `main` and on PRs out of draft, not on every draft push.

Neither makes the gate on a merge weaker than the gate on `main`, which is the line that does not move:
a draft cannot be merged, so everything that lands has been through macOS, and the full sweep on `main`
is weekly rather than absent. A PR gate weaker than the gate on `main` is the failure mode this repo is
about, and the way to cut a bill is to stop paying for the same answer twice, not to stop asking.

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
  it is also why a claim needs no lock: the only writer of a session's claim is that session. Read the
  second half narrowly - it is an argument about claims, not a property of the store. A handoff has two
  writers, the sender and whoever accepts or closes it, so `set_status` is a read-modify-write that two
  sessions can interleave. See #44; do not cite this bullet as licence for a new unlocked writer.
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

The PR title is what actually gets checked (`ci.yml`'s `pr-title` job): squash-merge makes it the
commit message on `main`, and that message is what `release-please.yml` reads to pick a version
bump and write a changelog entry. A title outside Conventional Commits is not caught anywhere else -
release-please just miscategorizes or drops it silently.

Versioning itself is `release-please.yml`, not a person deciding a number: it maintains a standing
PR computing the next semver bump and changelog from commits since the last release, and merging
that PR is the release. This project has never cut one yet, so the first merge of that PR is also
the first tag.

Two things about that PR that are not automatic. It needs "Allow GitHub Actions to create and approve
pull requests" ticked under Settings > Actions > General, or the workflow fails and no PR appears.
And it is opened with the workflow's own token, which by GitHub's design starts no workflow run, so
`ci` never reports on it and the ruleset will not let it merge. Close and reopen it as yourself,
`gh pr close N && gh pr reopen N`, and `ci` runs as it does on any other PR.

The first one is also curated by hand, once. release-please writes its section from commits and puts
it above the hand-written `Unreleased` one, which would leave everything this project did before
its first release below a version that already shipped it. So on that PR's branch the generated
section is replaced with the hand-written content under the release heading, the "nothing is
released yet" line goes, and the compare link, which points at a `v0.0.1` tag that was never cut,
is dropped. From the second release on, the generated section is the changelog.

The release also moves `version` in `plugin/.claude-plugin/plugin.json`, through `extra-files` in
`release-please-config.json`, and that is the number that matters most: the host caches an install
by it, so a change merged since the last release has not reached anyone who installed the plugin,
whatever `plugin update` says. `test_plugin_layout.py` fails if the config stops naming the file or
the manifest and the file disagree (#49).

Repeat the keyword for every issue a PR closes: `Closes #36, closes #27, closes #42`. GitHub parses only
the issue immediately after the keyword, so `Closes #36, #27, #42` closes one and silently ignores the
rest. #56 shipped with that shape in both the PR body and the squash message, closed #36, left three
open, and nothing anywhere reported it - the merge succeeded and the PR said what it meant to do. The
failure is invisible unless you go and look at the issues, which is the same shape as everything else
in this file.

And keep those keywords out of prose that is only mentioning an issue. The squash message for #59
ended `Found and filed rather than fixed: #60, #61, #62, #63, #64` and closed #60: `fixed: #60` is
exactly the form GitHub looks for, and the four after it survived only because a comma is not a
keyword. That is the rule above paying off in the one direction nobody wanted. A list of issues a PR
is *not* fixing has to be phrased away from the words - `still open after this: #60, #61` - and the
same goes for `closed` and `resolved` in a sentence about something else. Both halves of this fail
silently, one by closing nothing and one by closing what is still broken, and the merge looks
identical either way.

Branch and PR for everything is enforced rather than trusted: a ruleset on `main` requires a pull
request and a green `ci`, blocks force pushes and branch deletion, and has no bypass actors, so a
direct push is rejected for the owner too. Zero approvals are required, because an approval only the author could give is one
that gets bypassed, and a gate routinely bypassed teaches that gates are optional.

`mutate` is the one job kept out of `checks` without a permissions reason for it, against the
arithmetic below: it runs the suite once per mutation, and its failure names a rule nothing asserts
rather than a rule broken, which is not what "checks failed" would say. That costs one Linux minute
per run: `checks` comes in well under a minute, so folding a minute of sweep into it stays inside two
billed minutes while splitting them bills three. The price is named in the job's own comment rather
than argued away, which is what the first version of it did - and narrowing the sweep to the modules a
change could have broken made that price worse, not better, because most runs now sweep one module or
none and finish inside the same minute `checks` does. The reasons for the split did not change; the
rate did, and the comment says so.

`ci` is the aggregate job at the bottom of the workflow, and it is the only check the ruleset names.
That is deliberate: naming the jobs individually would put every OS and Python version into a repo
setting, so dropping one would block `main` forever on a check that can never report again - which is
what splitting `test-macos` out of the matrix would have done if the ruleset named anything else. Add a
job to the workflow and add it to `ci`'s `needs`, or it gates nothing. A step inside `ci` asserts that
now, because for eleven jobs and four consolidations the rule was kept by hand, on the one list every
other gate hangs off, and forgetting it looks exactly like remembering it: the job runs, reports, goes
red, and the merge button stays green. Inside `ci` rather than in `checks`, where it was first written,
because from there the one name it could not check was `checks` - and it also means the assertion is
part of the only check the ruleset requires.

A job that runs conditionally is `skipped` on the runs where its condition is false, and `ci` reads a
skip as a failure unless the job is named in `MAY_SKIP` in that same assert step. Adding a job with an
`if:` therefore means editing two things, which is the point: `MAY_SKIP` is written down there and also
derived from which jobs carry an `if:`, and the step fails when the two disagree. Derived alone, adding
an `if:` would silently buy a job permission to skip. Written alone, the name outlives the `if:` and the
gate starts reading "skipped because something upstream broke" as a pass. The exemption is only ever
safe for a job whose condition can be false on a **passing** run - `test-macos` skips on a draft PR,
and a draft cannot be merged.

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
