# Installing

Two steps that are genuinely separate, and conflating them is the mistake worth avoiding: **installing
the plugin** puts code and wiring on a machine, and **marking a root** decides where state lives and
which sessions can see each other. Installing on its own does nothing observable, on purpose.

## 1. Install the plugin

From GitHub, which needs read access to the private repo:

```
/plugin marketplace add teerakarna/session-exchange
/plugin install session-exchange@session-exchange
```

From a clone, which needs neither access nor auth, and is the better option while the repo is moving:

```
/plugin marketplace add ~/projects/personal/session-exchange
/plugin install session-exchange@session-exchange
```

The marketplace and the plugin share a name; `session-exchange@session-exchange` is not a typo.

Either way the whole repo lands at `~/.claude/plugins/marketplaces/session-exchange/`, and the plugin
itself is the `plugin/` subdirectory of that. The hooks find their own code through
`CLAUDE_PLUGIN_ROOT`, so nothing needs a path configured.

Nothing is written to `~/.claude/settings.json`. The hooks are declared in the plugin's own
`hooks/hooks.json` and travel with it, which is the reason this is a plugin rather than four scripts and
a settings edit.

**Restart the session, or start a new one.** `SessionStart` has already fired for the session you
installed from.

## 2. Mark a root

A root is a directory containing `.claude/exchange.json`. From anywhere inside the tree you want
coordinated:

```sh
python3 ~/.claude/plugins/marketplaces/session-exchange/plugin/lib/cli.py init
```

It prints the directory it would mark, anything else it considered, and anything it is refusing, before
writing. What it is choosing between:

- It defaults to the nearest ancestor holding a `CLAUDE.md`, strictly *above* the enclosing git repo. A
  repo-scoped exchange coordinates nothing, because the sessions that need to see each other are in
  sibling repos.
- It refuses a directory whose sibling children are themselves workspaces rather than repos. Marking
  that one directory would give each workspace sight of the others' sessions and handoffs, which is the
  single thing root resolution exists to prevent. `--force` gets past it and says so.

Pass a directory explicitly if you disagree with the default: `init /path/to/tree`.

For a one-off or a single pane, `CC_EXCHANGE_ROOT` overrides everything and needs no marker at all.
Useful for trying it somewhere without leaving a file behind.

## 3. Check it worked

```sh
python3 ~/.claude/plugins/marketplaces/session-exchange/plugin/lib/cli.py doctor
```

What to read in the output:

- `root` names the directory and **the rule that resolved it**. If that says `by marker` and points
  somewhere you did not expect, resolution walked further up than you thought.
- `steps` lists all seven migration steps derived from live state. `[?]` means the check is not
  answerable from here and prints why, rather than being omitted: a diagnostic that quietly skips a
  check reads exactly like one that passed it.
- `DOUBLE FIRE` means a legacy hook is still wired alongside the plugin. Presence and handoffs will
  render twice, and a stalled migration becomes indistinguishable from a finished one. This also
  appears in every session's injected context until it is gone.

Then start a new session in the tree and confirm a claim appeared:

```sh
ls <root>/.claude/exchange/sessions/
```

Silence with no root marked is correct and not a fault. If `doctor` says there is no environment root
and you meant there to be one, you are below a marker that does not exist, or above the one you made.

## Per machine, and what is shared

The plugin is installed per machine. The root marker and everything under
`<root>/.claude/exchange/` lives in the tree, so if that tree is a repo, decide deliberately whether
the state is committed or ignored. Claims are ephemeral and machine-specific; handoffs are the part
with durable value.

Sessions never read across roots in either direction, so two trees on one machine stay separate with no
configuration, and the same plugin serves both.

## An alias, if you use it at the terminal

The plugin deliberately does not put anything on your PATH. A plugin that edits a shell profile has
overstepped, and the path is stable enough to alias yourself:

```sh
alias exchange='python3 ~/.claude/plugins/marketplaces/session-exchange/plugin/lib/cli.py'
```

In a session, use `/exchange` instead; it resolves its own location and needs no alias.

## Backing it out

```
/plugin uninstall session-exchange
/plugin marketplace remove session-exchange
```

That removes the code and the wiring. State is left alone, because deleting somebody's handoffs as a
side effect of uninstalling a tool would be the wrong default. To remove it too:

```sh
rm -rf <root>/.claude/exchange <root>/.claude/exchange.json
```

Check what is in `<root>/.claude/exchange/` first. `EXCHANGE.md` is hand-maintained narrative and is the
one file in there nothing can regenerate.
