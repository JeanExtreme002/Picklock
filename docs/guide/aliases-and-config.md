# Aliases and settings

Both persist. Set them once and they are there next time you open the shell,
which is the point — a setting you have to type every session is a setting you
stop using.

## Settings

```
picklock> config:list
+----------------+---------+-----------------------------------------------+
| SETTING        | VALUE   | DESCRIPTION                                   |
+----------------+---------+-----------------------------------------------+
| limit          |      20 | Rows printed per result table (0 = no limit).  |
| max_results    | 1000000 | Scan hits kept in memory (0 = no cap).        |
| hex            |     off | Print integer values in hexadecimal.          |
| timing         |      on | Print the elapsed time after each command.    |
| progress       |      on | Show a progress line while scanning.          |
| writable_only  |     off | Scan only writable regions (faster).          |
| hex_width      |      16 | Bytes per line in 'memory:hex' output.        |
| watch_interval |     0.5 | Seconds between 'memory:watch' samples.       |
+----------------+---------+-----------------------------------------------+
```

```
config:set limit 50        change one
config:set hex on          booleans take on/off, true/false, 1/0
config:reset limit         put one back to its default
config:reset               put them all back
```

The two worth knowing about:

- **`writable_only`** — makes `--writable` the default for every scan. If you
  are always scanning for values that change, turn it on and stop typing it.
- **`max_results`** — the cap on how many hits a scan keeps in memory. A loose
  first scan on a big process can match tens of millions of addresses, and the
  cap is what stops that from becoming a swap storm. The scan says when it hit
  the cap.

## Aliases

Your own names for commands:

```
picklock> alias:add r memory:read
picklock> alias:add hp scan:next --decreased

picklock> r #1 int32
```

An alias stands for the first word of a line, and is substituted before
anything else looks at it — so `r --help` describes `memory:read`, and
arguments you type are appended to the ones the alias carries.

```
alias:list             what you have defined, and where they are stored
alias:remove r
```

A name that is already a command or an existing alias is refused, so you cannot
shadow `scan:value` with something that surprises you three weeks later.

## Where they live

```
$XDG_CONFIG_HOME/picklock/     ~/.config/picklock/ by default
%APPDATA%\picklock\            on Windows
```

as `aliases.json` and `settings.json`. `alias:list` and `config:list` print the
path they are using, so you never have to guess.

Two details:

- **`PICKLOCK_CONFIG_DIR`** moves both. It is the flag to reach for in CI, or
  when you want a session that cannot touch your real configuration.
- **Only settings you changed are stored.** A default that moves in a later
  release still reaches you, instead of being frozen by a file that recorded
  the old value for no reason.

If either file cannot be read or written — a read-only home directory, a
corrupt file — Picklock says so once and carries on with defaults. Losing your
aliases is not a reason to be unable to start the shell.
