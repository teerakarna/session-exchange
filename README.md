# session-exchange

Presence and handoffs between concurrent Claude Code sessions, as a Claude Code plugin.

Two things it answers, which are the two things a session actually needs from its siblings:

- **Presence** - is anyone else working in here right now, and on what. Rendered from the native
  session registry at `~/.claude/sessions/*.json`, not maintained by hand.
- **Handoffs** - does another session need something from me. Addressed to a repo-and-paths scope
  rather than to a hand-typed lane name, schema'd, and read at session start.

## Why it is a plugin

A plugin declares its own hooks in its own manifest, so the wiring travels with the code and
nothing has to write `~/.claude/settings.json`. That matters on a machine where `settings.json` is
owned by something else. Reach was never the problem; wiring was.

## Plugin, root, and the split between them

**The plugin is code and wiring. The environment root is state and config.** That split is the
portability, and it is why nothing in here names a path.

A root is any directory containing `.claude/exchange.json`. Resolution, highest precedence first:

1. `CC_EXCHANGE_ROOT` - a per-pane override, no marker needed.
2. The nearest ancestor of the session's cwd carrying the marker. Nearest, so nested roots resolve
   to the innermost.
3. Nothing. Silent no-op, and nothing is ever created implicitly. If no exchange context is
   injected, this environment has no exchange and there is nothing to do.

Sessions never read across roots, in either direction. `exchange init` defaults to the nearest
ancestor `CLAUDE.md` directory strictly *above* the enclosing git root, because a repo-scoped
exchange coordinates nothing - the sessions that need to see each other are in sibling repos. It
refuses a directory whose sibling children are themselves areas rather than repos, since marking
that would merge two workspaces that are meant to stay apart.

## State

| Written by | Format | Path |
|---|---|---|
| Hooks and CLI | JSON, schema'd | `<root>/.claude/exchange/sessions/<session_id>.json` |
| Hooks and CLI | JSON, schema'd | `<root>/.claude/exchange/handoffs/<id>.json` |
| Humans and sessions | Markdown | `<root>/.claude/exchange/EXCHANGE.md` |

One file per session, never a shared append target - concurrent writers otherwise contend. No regex
ever parses hand-typed structure again. The markdown keeps narrative, decisions and history, which
is what a ledger is genuinely good at.

## Status

Early. What exists today is root resolution and the regression suite for the parser this replaces.

```
python3 plugin/tests/run.py
```

`test_handoff_parser.py` exercises the legacy hook still running on one machine and **skips** if it
is absent, so the suite is green on a machine that never had it. It is here because the port has to
keep it passing.

## Design and history

The design, the migration steps and the evidence for each one live with the plan, in the dotfiles
repo under `plans/2026-09-25_portable-session-exchange*`. The short version of what is being
replaced: four unversioned shell and Python scripts on one laptop, matching hand-typed lane names
against a 141 KB hand-maintained markdown file with a regex, which matched zero entries for ten days
without being able to say so.

## Testing discipline

One rule, and it is load-bearing here rather than decorative: **a check has to be able to fail.**
Every gate gets broken deliberately once, and what the failure looks like gets recorded. A test that
passes identically whether the behaviour is implemented or not is asserting nothing, and it looks
exactly like a test that passes. That is the failure mode this whole project exists to remove, so it
is not allowed back in through the test suite.
