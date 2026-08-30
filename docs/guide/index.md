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

## Finding a command

When you do not know what to type, type `help`.

| Type this | You get |
| --- | --- |
| `help` | the namespaces above |
| `help scan` | the commands in that namespace |
| `help scan:value` | what that one command takes |

So you go from "what can this do?" to "how do I run this?" in two steps,
without ever being shown forty commands at once.

There are shorter ways to reach the same pages, if they suit your fingers
better: a namespace on its own (`scan`) prints its commands, and any command
takes `--help`.

Those pages are built from the command itself, so they cannot be out of date:
if a command accepts a flag, the flag is on its help page.
