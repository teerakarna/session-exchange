---
description: Presence and handoffs across concurrent sessions - show who else is here, state what this session is working on, or check the exchange's health
argument-hint: show | claim <what you are doing> | init | doctor
allowed-tools: Bash(python3:*)
---

Run the `exchange` CLI for the user and report what it says.

```
python3 "${CLAUDE_PLUGIN_ROOT}/lib/cli.py" $ARGUMENTS
```

With no arguments, run `show`.

## The subcommands

- `show` - the resolved root, who else holds a claim under it, and what is waiting. A `!` marks a
  claim whose session is no longer in the registry, which means stale rather than current.
- `claim --focus "..." [--repo X] [--path Y] [--ticket Z]` - state what this session is doing.
  Repos, paths and tickets add to what is already claimed rather than replacing it, so picking up a
  second repo mid-task does not mean restating the first. `--set-path` replaces, and `--clear-paths`
  empties.
- `init [path]` - mark a directory as an environment root. Prints the default and the alternatives
  before doing anything, and refuses a directory whose subdirectories are separate workspaces.
- `doctor` - live state with evidence: which root resolved and by which rule, which legacy scripts
  are still on disk or still wired, and which migration step is the first one outstanding.
- `handoff` and `migrate` exit 2 and say which step builds them. Exit 2 is not a failure; it means
  the command does not exist yet.

## What to do with the output

Relay it plainly. Three things are worth calling out to the user rather than passing through:

- **DOUBLE FIRE** in `doctor` means legacy hooks are still wired and rendering alongside this
  plugin. Say so directly; it is the state in which a stalled migration looks finished.
- A stale claim means somebody's session ended without clearing up. It is safe to ignore and worth
  mentioning once.
- Any line beginning `problem` is the exchange telling you it could not read something. Never
  summarise those away: the entire reason this tool exists is that a component which could not read
  its input exited 0 for ten days and nobody could tell.

## What not to do

Do not write to `.claude/exchange/` directly, and do not hand-edit a claim or a handoff file. They
are schema-validated on write, and going round the CLI is how an invalid file reaches disk where a
reader then has to guess whether it is corrupt or simply newer.

Do not claim on the user's behalf without being asked. A claim is a statement of intent, and a
guessed one is worse than none.
