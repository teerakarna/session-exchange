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
  from the source they claim to patch. Twenty-three mutations across `hookio`, `store` and `validate`,
  with `UNSWEPT` naming the eight modules still owed a table. Pointing it at `hookio` found nine live
  rules there, two of them guards in `payload` wide enough to let a hook exit 1 with a traceback.

### Not built yet

- `exchange handoff` and `exchange migrate` exit 2 and name the step that builds them. Exit 2 is
  neither success nor failure: a command that does not exist must not report either.
- `Stop` is deliberately unwired. Its only job is catching handoffs posted mid-session, and until the
  matcher exists it could only spawn a process per turn to do nothing.
