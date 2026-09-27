# Changelog

Format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/spec/v2.0.0.html). Nothing is released yet, so there is one section.

## [Unreleased]

### Added

- Root resolution. `CC_EXCHANGE_ROOT`, then the nearest ancestor carrying `.claude/exchange.json`,
  then nothing at all. The third case is silent and creates no files: if no exchange context is
  injected, this environment has no exchange.
- `SessionStart` seeds this session's claim and warns, every session, while a legacy hook is still
  wired alongside the plugin.
- `SessionEnd` clears the claim, so a stale row is not something anybody has to remember to delete.
- `exchange init | show | claim | doctor`. `init` refuses a directory whose sibling children are
  themselves workspaces, because marking that would show each of them the others' sessions.
- JSON schemas for the marker, claims and handoffs, with a validator that covers only the subset of
  JSON Schema they use and raises on any keyword it does not implement.
- `doctor` derives all seven migration steps from live state, and prints `[?]` with a reason for the
  ones it cannot answer rather than omitting them.
- Repository hygiene: Apache-2.0, CI on Linux and macOS across Python 3.9 to 3.13, ruff, shellcheck,
  gitleaks, a gate asserting the runtime imports nothing but the standard library, and dependabot.
- A mutation sweep as a CI gate. `plugin/tests/mutate.py` breaks one rule at a time and requires the
  suite to notice; `test_mutations.py` is the cheap half that keeps the tables from drifting away
  from the source they claim to patch. A hundred and thirty-eight mutations across `claims`,
  `exchange_root`, `hook`, `hookio`, `legacy`, `registry`, `store` and `validate`; the three modules
  with no table are all in `DECLINED`, with the reason recorded next to each. Every table has found
  live rules on its first run: two guards in `hookio.payload` wide enough to let a hook exit 1 with a
  traceback, ten unasserted rules in root resolution, every failure path of `seed`, `update` and
  `clear` in `claims`, and five rules in `legacy` that the end-to-end fixtures were assumed to hold
  up and do not. `registry` had no test file at all, and now has forty checks.

### Fixed

- `show` renders every list a claim holds. `claim --repo` and `--ticket` were accepted, validated and
  written, and no reader displayed them, so half the scope a handoff is addressed to was invisible to
  the people it is addressed to. Each list is capped by `max_hot_paths` as paths already were, and
  what the cap leaves out is now counted rather than dropped in silence.
- `doctor` says `marker absent` instead of `marker valid` when there is no marker. `store.config`
  returns the schema defaults and no problem in that case, which is right for a renderer and was
  being printed as though a file had been read; the line also contradicted step 5 immediately below
  it. Reachable only through `CC_EXCHANGE_ROOT`, since the walk finds a root by finding the marker.

### Not built yet

- `exchange handoff` and `exchange migrate` exit 2 and name the step that builds them. Exit 2 is
  neither success nor failure: a command that does not exist must not report either.
- `Stop` is deliberately unwired. Its only job is catching handoffs posted mid-session, and until the
  matcher exists it could only spawn a process per turn to do nothing.
