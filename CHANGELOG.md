# Changelog

Format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/spec/v2.0.0.html). Nothing is released yet, so there is one section.

## [0.1.0](https://github.com/teerakarna/session-exchange/compare/v0.0.1...v0.1.0) (2026-10-01)


### Added

* **ci:** automate versioning with release-please ([#84](https://github.com/teerakarna/session-exchange/issues/84)) ([b16e780](https://github.com/teerakarna/session-exchange/commit/b16e780b61c0d2370f2bc5647c9eab1ef19c088f))
* **handoff:** the write path, with status derived from history ([#41](https://github.com/teerakarna/session-exchange/issues/41)) ([762ceee](https://github.com/teerakarna/session-exchange/commit/762ceee421977d3045d41e6e95ba534bf2289e24))
* **hook:** match handoffs to the session they are for ([#81](https://github.com/teerakarna/session-exchange/issues/81)) ([cac92dd](https://github.com/teerakarna/session-exchange/commit/cac92ddef39f50c4da9671b0cc601844757dafbf))
* **hook:** render presence at session start ([#80](https://github.com/teerakarna/session-exchange/issues/80)) ([41b7fc6](https://github.com/teerakarna/session-exchange/commit/41b7fc6a0b387dbcddc7ee699992a977d69cad9e))
* **import:** key entries so a second import updates rather than duplicates ([#6](https://github.com/teerakarna/session-exchange/issues/6)) ([f2aa4a9](https://github.com/teerakarna/session-exchange/commit/f2aa4a9b7707d24b55bbb763634af10be5625986))
* **ledger:** parse the live handoff shapes ([#5](https://github.com/teerakarna/session-exchange/issues/5)) ([06e87fc](https://github.com/teerakarna/session-exchange/commit/06e87fc9cda35acc8d2b729c527d4f212584e6fd))
* plugin skeleton, hooks manifest, schemas and the exchange command ([#1](https://github.com/teerakarna/session-exchange/issues/1)) ([480a475](https://github.com/teerakarna/session-exchange/commit/480a4753aede0c28755c6e0fd9deae4781790f31))
* root resolution, and the regression suite it inherits ([269b57d](https://github.com/teerakarna/session-exchange/commit/269b57dd2835e6d0adad0687373287cdb0dacf99))


### Fixed

* a stdout nobody is reading is silence, not a traceback on the way out ([#20](https://github.com/teerakarna/session-exchange/issues/20)) ([985e423](https://github.com/teerakarna/session-exchange/commit/985e423a254f59bcb7e9ea44083af071c8c9c492))
* **cli:** refuse a claim from inside a background job ([#83](https://github.com/teerakarna/session-exchange/issues/83)) ([8b316a0](https://github.com/teerakarna/session-exchange/commit/8b316a0c7ff5a4f623399f7624de55b65e54d058))
* **cli:** report what the files actually say, not what the defaults imply ([#29](https://github.com/teerakarna/session-exchange/issues/29)) ([d95b33f](https://github.com/teerakarna/session-exchange/commit/d95b33f12f07c7ba987ba27c4982dd12f7f72322))
* **handoff:** a record one session writes is data to every other one ([#59](https://github.com/teerakarna/session-exchange/issues/59)) ([87611d0](https://github.com/teerakarna/session-exchange/commit/87611d0cc8511410a0eff5872ccb1df041cbd0a7))
* **handoff:** a status change is its own file, so a concurrent move is not lost ([#50](https://github.com/teerakarna/session-exchange/issues/50)) ([bcae4fb](https://github.com/teerakarna/session-exchange/commit/bcae4fb239c26af39941fc0cfbf455aa1fbac32f))
* **init:** an area directory can mark itself, and the merge-point refusal stays ([#37](https://github.com/teerakarna/session-exchange/issues/37)) ([6e766e9](https://github.com/teerakarna/session-exchange/commit/6e766e9651e884be897b6844c45be5f01106553a))
* **legacy:** report a machine-wide wiring as what it is, not as this root doubling ([#35](https://github.com/teerakarna/session-exchange/issues/35)) ([4f477e3](https://github.com/teerakarna/session-exchange/commit/4f477e39b721758478d2e2cf26166cc749a4e705))
* refuse to start a sweep from inside a sweep ([#19](https://github.com/teerakarna/session-exchange/issues/19)) ([e933215](https://github.com/teerakarna/session-exchange/commit/e9332150b1d0cc267db33ce362149b89319801a0))
* **release:** move plugin.json's version with each release, and name it in doctor ([#85](https://github.com/teerakarna/session-exchange/issues/85)) ([75f3b30](https://github.com/teerakarna/session-exchange/commit/75f3b3016e0509609416b2cd20b6a3899d04989b))
* **store:** every anchored pattern accepted a trailing newline ([#9](https://github.com/teerakarna/session-exchange/issues/9)) ([4639d70](https://github.com/teerakarna/session-exchange/commit/4639d70da3795d78fc7edc3252e447cd8f737f7a))
* **store:** strip filenames in problem lines ([#82](https://github.com/teerakarna/session-exchange/issues/82)) ([0a96ccf](https://github.com/teerakarna/session-exchange/commit/0a96ccf3b49c2533f6eab5e32f904b4a649d063f))

## [Unreleased]

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
