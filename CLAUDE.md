# session-exchange

Presence and handoffs between concurrent Claude Code sessions, as a Claude Code plugin. Read
`README.md` for the design and `CONTRIBUTING.md` for how to test, which is the part of this repo most
likely to be got wrong. This file holds only what a change or a review cannot work out from the code.

The seven migration steps are not written out in any doc: `exchange doctor` prints them derived
from live state, which is the one copy that cannot go stale.

## Rules that are not obvious from the code

- **Nothing in `plugin/` may name a path, a repo, a lane, a person or an environment.** The plugin is
  code and wiring; the root is state and config. That split is the portability, and a hardcoded path is
  the exact bug class this project exists to delete.
- **The same rule holds in the docs and the fixtures, where it is easier to break.** Write
  `/path/to/your/session-exchange`, never a real clone location: a reader copying a path out of a README
  that happens to work for the author is being told the layout is required when it is not. Fixture
  directories are named for the shape they test (`container/alpha`), never after any real workspace,
  because a fixture that mirrors one machine's tree reads as a supported layout. Both were violated once
  and fixed; the author's own paths are the thing to grep for before a push.
- **Assume the standard, allow the override, and keep the override machine-local.** Every knob has a
  working default so the tool does something sensible with no configuration at all, and the defaults are
  read from `plugin/schemas/exchange.schema.json` by `store.config()` rather than restated in Python, so
  the standard is stated exactly once. Customisation lives in `<root>/.claude/exchange.json` and
  `CC_EXCHANGE_ROOT`, both outside the plugin and both specific to the machine they are on. If you find
  yourself adding a default to code, put it in the schema instead. If you find yourself needing a knob
  the schema cannot express, that is a design question, not a place for a constant.
- **Legacy detection is by shape, never by literal name.** Two of the scripts being replaced carry one
  environment's project prefix, which must not appear in a generalised tool. A glob also survives a
  rename, and the fixtures are named by shape for the same reason.
- **The legacy scan reports a settings path and a bare script name, never the command string.** A
  command string is where somebody's arguments are.
- **A hook must never fail a session start.** Every handler is wrapped, always exits 0, and reports
  problems in the injected context. A bad root resolves to no root and says why. That covers the reader
  as well as the input: with nobody reading stdout the bytes sit in the buffer and the interpreter's own
  shutdown flush fails, after `main` has returned 0 and where nothing can catch it, so `emit` flushes
  while it still can and points fd 1 at devnull if that fails. Wrapping the `print` instead does not
  work, and it looks like it does.
- **Silence is a real answer.** No root means no output and no files. Do not add a header, a heading or
  an "all clear" line that appears every session: a section that is usually empty is a section the
  reader stops looking at, which is the failure being fixed.
- **Echo the hook event name back from the payload, not from the wiring.** A mismatch makes Claude Code
  drop the injected context, silently.
- **Standard library only, in `plugin/lib/`.** The handlers invoke whatever `python3` is on PATH with no
  chance to install anything, so a third-party import is an `ImportError` at session start on every
  machine but this one. Floor is 3.9, which is what a stock macOS ships. CI gates both.
- **Add fields to the schema, not to a hand-written check.** `plugin/lib/validate.py` covers only the
  subset of JSON Schema the files use and raises on any keyword it does not implement, with a meta-test
  asserting every keyword in use is covered. That property is the only reason hand-rolling it is
  defensible: the failure mode of a partial validator is a constraint that quietly does not run.
- **`status` in the native registry is per-turn.** `idle` means "not mid-turn", not "finished". That is
  why claims exist alongside it, and why a claim is not inferred from status.
- **Roots never read each other**, in either direction. The test for it must never regress.

## Things left undone on purpose, so do not "fix" them

- **`Stop` is unwired.** Its only job is catching handoffs posted mid-session. The matcher it would call
  exists, but a hook on every turn is a cost every session pays, so it goes in as its own reviewed change.
- **`handoff` and `migrate` exit 2** and name the step that builds them. Exit 2 is neither success nor
  fault.
- **No `pyproject.toml`.** Nothing pip-installs this and there is no distribution to build, so
  packaging metadata would be a claim the repo cannot honour. Ruff config lives in `ruff.toml`.

## Working rules for this repo

- **Run `python3 plugin/tests/run.py` and `/code-review` on the diff before opening a PR**, sized to the
  change: low for docs, plans or a fixture rename, high for anything under `plugin/lib/`,
  `plugin/hooks-handlers/`, `plugin/schemas/` or `.github/workflows/ci.yml`. Green CI is necessary and
  not sufficient, and this repo is the reason that distinction has a name. The suite was green while
  `hookio.event_name` could be cut down to `return default`, green while eight schema patterns accepted a
  trailing newline they were written to exclude, and green across eleven jobs that finished in
  twenty-eight seconds of wall time and billed twenty-nine minutes. Not one of those is something a test
  run can tell you. Re-run after fixing what it finds, because a second pass has caught a bug the first
  pass's own fix introduced, and stop when a pass comes back clean rather than after a set number of
  rounds. Scope the re-run to what the fix touched and size it off that, not off the original diff:
  as first written this bullet pinned `high` to the paths the whole diff covered, which put eleven
  `high` passes on one PR whose last rounds changed only prose in `CONTRIBUTING.md`. A clean stop
  with no cost ceiling terminates on the wrong axis. When a pass's only findings are in the harness's
  scoring or in the wording rather than in behaviour, that is the point to read the diff yourself
  instead of spending another pass, and to say in the PR body that you did. If the review cannot
  complete, say so plainly in the PR body instead of describing the automated gate as a review - two
  delegated passes on that PR died on a watchdog and returned nothing, which costs the same as a pass
  that found something.
- **Point the review at the checks the diff adds, not only at the code.** The load-bearing rule at the
  top of `CONTRIBUTING.md` can be satisfied on paper: a PR can name a gate it broke and paste output
  that does not actually demonstrate the thing it claims, which is how a suite reads as thorough while
  five rules in a seventy-line module are unasserted. So the review is also asked, of every check being
  added, whether it would notice its own absence, and whether the recorded failure is what that check
  really prints.
- Branch and PR for everything; nothing lands on `main` directly. Conventional commits. No
  `Co-Authored-By` trailers. A ruleset enforces this with no bypass actors, so a direct push is
  rejected rather than merely discouraged, and there is no point attempting one.
- **A new CI job must be added to the `ci` job's `needs`, or it gates nothing.** `ci` is the single
  aggregate check the ruleset requires, so that renaming a matrix leg cannot block `main` on a check
  that will never report again. A job outside its `needs` can fail while the merge button stays green.
- Keep a PR readable in one sitting. The skeleton PR was 2249 lines and got away with it only because
  it was all new code with nothing to regress.
- Plain `-`, never an em dash or an en dash, in prose and code comments alike.
