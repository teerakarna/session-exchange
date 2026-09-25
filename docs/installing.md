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

From a clone, which needs neither access nor auth, and is the better option while the repo is moving.
Wherever you keep clones is where this goes; nothing in the plugin cares:

```
/plugin marketplace add /path/to/your/session-exchange
/plugin install session-exchange@session-exchange
```

The marketplace and the plugin share a name; `session-exchange@session-exchange` is not a typo.

### The two paths, because they are easy to confuse

Installing produces files in two places, and only one of them is the plugin:

| Path | What it is |
|---|---|
| `~/.claude/plugins/marketplaces/session-exchange/` | the **marketplace clone**: the whole repo, including tests, docs and CI. One per marketplace, not per plugin |
| `~/.claude/plugins/cache/session-exchange/session-exchange/<version>/` | the **installed plugin**: a copy of the repo's `plugin/` directory, and what `CLAUDE_PLUGIN_ROOT` resolves to |

`~/.claude/plugins/installed_plugins.json` records the second as `installPath`, along with the commit it
came from, which is the authoritative answer on any machine.

Note the `<version>` in the second path. It comes from `plugin/.claude-plugin/plugin.json`, so it
**changes on every version bump**. Do not hardcode it anywhere.

The hooks need neither path. They find their own code through `CLAUDE_PLUGIN_ROOT`, which is why nothing
in this plugin has a path configured.

Nothing is written to `~/.claude/settings.json`. The hooks are declared in the plugin's own
`hooks/hooks.json` and travel with it, which is the reason this is a plugin rather than four scripts and
a settings edit.

**Restart the session, or start a new one.** `SessionStart` has already fired for the session you
installed from.

## 2. Mark a root

A root is a directory containing `.claude/exchange.json`. From anywhere inside the tree you want
coordinated:

```
/exchange init
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

```
/exchange doctor
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

In a session, use `/exchange`: it resolves its own location through `CLAUDE_PLUGIN_ROOT` and needs no
alias, no PATH entry and no configuration. Everything below is only for a shell prompt.

The plugin deliberately puts nothing on your PATH, because a plugin that edits a shell profile has
overstepped. Adding an alias yourself is fine, but not pointed at the installed copy: that path carries
the plugin version and breaks silently at the next bump, which is the worst kind of break for something
you type from memory.

Point it at a clone instead. The clone is what you edit and test against anyway, and it has no version
in its path:

```sh
alias exchange='python3 /path/to/your/session-exchange/plugin/lib/cli.py'
```

If you would rather run the copy that is actually installed, derive the path rather than typing it, so
it survives a version bump:

```sh
exchange() {
  local root
  root=$(python3 -c '
import json, pathlib
data = json.loads((pathlib.Path.home() / ".claude/plugins/installed_plugins.json").read_text())
entries = data["plugins"]["session-exchange@session-exchange"]
print(max(entries, key=lambda e: e["installedAt"])["installPath"])
') || return 1
  python3 "$root/lib/cli.py" "$@"
}
```

Both run the same code while the clone is in sync with what is installed. When they are not, the second
is the honest one, which is the whole reason to prefer it while the plugin is still moving.

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
