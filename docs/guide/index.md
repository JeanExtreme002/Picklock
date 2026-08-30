# User guide

The shell in depth, one subject at a time. Each page is a workflow rather than
a list of flags — the flags are in the
[Command reference](../reference/commands.md), generated from the code.

If you have not run Picklock yet, the [Quick start](../quickstart.md) is the
five-minute version of the first four pages here.

```{toctree}
:maxdepth: 1

attaching
scanning
addresses
reading-writing
pointers
inspecting
aliases-and-config
scripting
```

## How the shell is arranged

Every command is named `namespace:command`. There are six namespaces and a
handful of commands that belong to no namespace because they are about the
session rather than about a target:

| Namespace | What it is for |
| --- | --- |
| `ps:` | finding a process and attaching to it |
| `memory:` | reading, writing and looking at memory |
| `scan:` | searching for values, and narrowing the results |
| `pointer:` | pointer chains and pointer scans |
| `alias:` | your own names for commands |
| `config:` | settings, which persist between sessions |
| *(none)* | `help`, `source`, `version`, `clear`, `exit` |

Help comes in three layers, so you are never shown forty commands at once:

```
help                 the namespaces, and the session commands
scan                 (or 'help scan') the commands in one namespace
help scan:value      one command's arguments
```

The last of those is generated from the parser the command actually runs with,
so a flag that exists is a flag that shows up. `scan:value --help` prints the
same page.
