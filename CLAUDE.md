# session-exchange

Presence and handoffs between concurrent Claude Code sessions, as a Claude Code plugin. Read
`README.md` for the design and `CONTRIBUTING.md` for how to test, which is the part of this repo most
likely to be got wrong. This file holds only what a change or a review cannot work out from the code.

The design, the seven migration steps and the evidence for each live with the plan, not here:
`plans/2026-09-25_portable-session-exchange*` in the `dotfiles` repo. `exchange doctor` prints the same
seven steps derived from live state.

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
  problems in the injected context. A bad root resolves to no root and says why.
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

- **`Stop` is unwired.** Its only job is catching handoffs posted mid-session and the matcher is step 4.
  Wiring it now spawns a process per turn to no-op.
- **`handoff` and `migrate` exit 2** and name the step that builds them. Exit 2 is neither success nor
  fault.
- **No `pyproject.toml`.** Nothing pip-installs this and there is no distribution to build, so
  packaging metadata would be a claim the repo cannot honour. Ruff config lives in `ruff.toml`.

## Working rules for this repo

- Branch and PR for everything; nothing lands on `main` directly. Conventional commits. No
  `Co-Authored-By` trailers.
- Keep a PR readable in one sitting. The skeleton PR was 2249 lines and got away with it only because
  it was all new code with nothing to regress.
- Plain `-`, never an em dash or an en dash, in prose and code comments alike.
