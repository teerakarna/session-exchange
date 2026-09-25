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

## The corollary, which cost more to learn

**Run the thing.** The two worst bugs in the first working version passed the whole suite: `claim`
took its display name from the calling session rather than the session being claimed for, so it wrote
someone else's claim under the caller's name and then reported it back as stale; and the `SessionStart`
handler read a payload field that does not exist. A green suite is not a demonstration. Use the
commands, read the output, and check it says something true.

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

Keep a PR readable in one sitting. The first one here was 21 files and 2249 lines, which got through
only because it was all new code with no existing behaviour to regress. That is a property of a
skeleton, not of the work after it.

Plain `-` rather than an em dash or an en dash, in code comments and prose alike.
