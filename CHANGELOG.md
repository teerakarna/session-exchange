# Changelog

Format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/spec/v2.0.0.html). 0.1.0 was written by hand; from the next release on,
each section is generated from the commits it ships.

## [0.3.0](https://github.com/teerakarna/session-exchange/compare/v0.2.0...v0.3.0) (2026-10-09)


### Added

* flag a catch where the file also crashed after its check ([#57](https://github.com/teerakarna/session-exchange/issues/57)) ([#102](https://github.com/teerakarna/session-exchange/issues/102)) ([167126b](https://github.com/teerakarna/session-exchange/commit/167126bd2f4293372a40c95b4916423552f8b6aa))


### Fixed

* init's git-root ceiling climbs past a repo nested in another ([#96](https://github.com/teerakarna/session-exchange/issues/96)) ([5d05417](https://github.com/teerakarna/session-exchange/commit/5d05417c1e2f2e0359a93fc17f7df4e57154723c))
* migrate names a stale moves directory instead of saying run it again ([#94](https://github.com/teerakarna/session-exchange/issues/94)) ([#100](https://github.com/teerakarna/session-exchange/issues/100)) ([dbe45db](https://github.com/teerakarna/session-exchange/commit/dbe45db69c86713259beae74f2ca06e2913302c7))
* review nits from [#41](https://github.com/teerakarna/session-exchange/issues/41) ([#98](https://github.com/teerakarna/session-exchange/issues/98)) ([22ce6d9](https://github.com/teerakarna/session-exchange/commit/22ce6d95a812e51d57884ae5b96124f25ffcc45d))

## [0.2.0](https://github.com/teerakarna/session-exchange/compare/v0.1.0...v0.2.0) (2026-10-02)


### Added

* migrate --step 4 imports the ledger's open handoffs ([#92](https://github.com/teerakarna/session-exchange/issues/92)) ([adb4d38](https://github.com/teerakarna/session-exchange/commit/adb4d383ae91e0a15678031adc3f0a111305f76b))
* migrate --step 7 unwires this root's legacy hooks and retires their scripts ([#95](https://github.com/teerakarna/session-exchange/issues/95)) ([040982e](https://github.com/teerakarna/session-exchange/commit/040982eaad399ca2136e42bf9865008250809bdf))
* step 4 is not applicable on a root that never had a ledger ([#90](https://github.com/teerakarna/session-exchange/issues/90)) ([fe06b20](https://github.com/teerakarna/session-exchange/commit/fe06b20543aff85b6d9a656a74eb47c33066eff4))

## [0.1.0] - 2026-10-01

### Added

- Root resolution. `CC_EXCHANGE_ROOT`, then the nearest ancestor carrying `.claude/exchange.json`,
  then nothing at all. The third case is silent and creates no files: if no exchange context is
  injected, this environment has no exchange.
- `SessionStart` seeds this session's claim and warns, every session, while a legacy hook is still
  wired alongside the plugin.
- `SessionStart` renders presence: every other live session under the root, with its focus and
  claimed scope, capped per the marker. A claim whose session is no longer running is counted, not
  shown as current, and a session alone under its root is injected nothing (#79).
- `SessionStart` renders the handoffs not yet closed that are for this session, newest first under
  `max_handoffs_listed`, and counts what the cap leaves out. A handoff is for a session named by its
  `session_id`, or working in its repo - claimed, or the repo its cwd is in, a linked worktree
  counting as its main repo - with `paths` narrowing that only for a session that claimed a path.
  Where in the repo the cwd is narrows nothing. Handoffs for other sessions are not mentioned;
  `exchange handoff list` has them. Scopes are compared after normalising both sides, so
  `./plugin/lib/` and `plugin/lib` are one scope, and records keep what their writer typed (#62).
- A scope refused for a leading `/` or a `..` no longer says it is relative to the root, which was
  wrong for `--path`: that is relative to the repo.
- `SessionEnd` clears the claim, so a stale row is not something anybody has to remember to delete.
- `exchange init | show | claim | doctor`. `init` refuses a directory whose sibling children are
  themselves workspaces, because marking that would show each of them the others' sessions.
- `exchange handoff post | accept | close | list`, the first thing here that writes state a
  *different* session reads. Two rules carry it. Posting never overwrites: an id already on disk is a
  refusal, because a dropped handoff is invisible at both ends - the sender saw it posted and the
  recipient never had it to miss - and the refusal is `os.link` rather than a check followed by a
  write, since a check and a write have a window between them that two senders can both fit through.
  And status is not a field at all: the record is written once and never touched again, while each
  move is its own file under `handoffs/<id>.d/`. Two sessions moving one handoff at the same moment
  therefore both get their move recorded rather than one of them losing it, and the pair is reported
  as concurrent and left alone rather than resolved, because guessing which came first is how a
  closed handoff comes back open, at whatever position the pair sits rather than only the newest.
  Ordering is one past the highest position a writer read, never the clock: timestamps here are
  seconds, and accepting then closing inside one second is ordinary. One past the highest rather than a
  count of what was read, so two writers acting on one state land on the same number - a count stops
  equalling the position as soon as one concurrent pair exists, which is exactly when the tie matters.
  A handoff's moves live under `<id>.d` and not the bare id, because an id may contain a dot and a
  directory named for one would sit where another id's record goes. The first
  shape of this kept `status` beside a `history` array inside the record and had the second writer
  append to it - which drops a concurrent move and, because the file left behind is internally
  consistent, reports nothing (#44). A record written in that shape is now refused by name rather
  than half-read. Because the id inside a record is what finds its moves, that id has to be the name
  of the file it was read from: a record holding somebody else's id is reported, and so is a second
  file claiming an id that already names one, since two inputs that agree cannot say which of them
  was read. A moves directory that outlived its record is a refusal to post over rather than a status
  a brand-new handoff silently inherits. `accept` and `close` are separate verbs rather than a
  `--status` flag, so taking
  something on cannot be typed as finishing it, and `handoff` has no default verb at all, so a typo
  cannot post or list by accident. `--body -` reads stdin, because a body with backticks in it does
  not survive being a shell argument. Addressing refuses every combination it cannot honour rather
  than honouring part of one: `--repo` with `--session`, `--path` without `--repo`, `--path` with
  `--session`, and nothing at all. The third of those was a silent truncation until review found it -
  the paths were dropped and the handoff posted, four lines above the refusal written for exactly
  that mistake.
- JSON schemas for the marker, claims and handoffs, with a validator that covers only the subset of
  JSON Schema they use and raises on any keyword it does not implement.
- `doctor` derives all seven migration steps from live state, and prints `[?]` with a reason for the
  ones it cannot answer rather than omitting them.
- Repository hygiene: Apache-2.0, CI on Linux and macOS across Python 3.9 to 3.13, ruff, shellcheck,
  gitleaks, a gate asserting the runtime imports nothing but the standard library, and dependabot.
- A mutation sweep as a CI gate. `plugin/tests/mutate.py` breaks one rule at a time and requires the
  suite to notice; `test_mutations.py` is the cheap half that keeps the tables from drifting away
  from the source they claim to patch. A hundred and ninety-one mutations across `claims`,
  `exchange_root`, `handoffs`, `hook`, `hookio`, `legacy`, `registry`, `store` and `validate`, one
  file each under `plugin/tests/tables/` so that adding a mutation sweeps the module it names instead
  of all nine. `cli` is the one module deliberately not swept, with the reason recorded next to it;
  `ledger` and `reconcile` are owed tables. A mutation caught by a file that died rather than by a
  failing check inside that file is still a catch - being mutated into raising is a legitimate way to
  be noticed - but it is counted and named at the end, because a file that stopped part way through
  asserted nothing after that point while the sweep reported the whole table as covered. Every
  table has found live rules on its first run: two guards in `hookio.payload` wide enough to let a
  hook exit 1 with a traceback, ten unasserted rules in root resolution, every failure path of
  `seed`, `update` and `clear` in `claims`, and five rules in `legacy` that the end-to-end fixtures
  were assumed to hold up and do not. `registry` had no test file at all, and now has forty checks.

### Fixed

- `show` renders every list a claim holds. `claim --repo` and `--ticket` were accepted, validated and
  written, and no reader displayed them, so half the scope a handoff is addressed to was invisible to
  the people it is addressed to. Each list is capped by `max_hot_paths` as paths already were, and
  what the cap leaves out is now counted rather than dropped in silence.
- `doctor` says `marker absent` instead of `marker valid` when there is no marker. `store.config`
  returns the schema defaults and no problem in that case, which is right for a renderer and was
  being printed as though a file had been read; the line also contradicted step 5 immediately below
  it. Reachable only through `CC_EXCHANGE_ROOT`, since the walk finds a root by finding the marker.
- A store filename is stripped before it reaches a problem line, in `show`, `handoff list` and the
  session start. Every name this plugin writes is safe already, so this is for a file an importer, a
  hand edit or another tool put there (#60).
- A release now reaches the installed copy. The host caches an install by the version in
  `plugin.json`, which had been `0.0.1` since the skeleton, so `plugin update` advanced the clone and
  left the hooks running a copy from before `handoffs.py` existed while reporting it as the latest.
  release-please now moves that version with every release, and `doctor` opens with the running
  version and the directory it runs from, which says in one line whether it is the cache (#49).
- `claim` from inside a background job is refused instead of overwriting the focus of the session
  that started it. `--session` still claims as that session on purpose (#68).

### Not built yet

- `exchange migrate` exits 2 and names the step that builds it. Exit 2 is neither success nor
  failure: a command that does not exist must not report either.
- `Stop` is deliberately unwired. Its only job is catching handoffs posted mid-session, and until the
  matcher exists it could only spawn a process per turn to do nothing.
