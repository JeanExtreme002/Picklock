# Picklock

<p align="center">
  <b>Read, write and scan the memory of a running process — from any terminal.</b><br>
  <i>One dependency. Three operating systems. No GUI, no compiler, no display.</i>
</p>

<p align="center">
  Runs on <b>Windows</b> · <b>Linux</b> · <b>macOS</b>
</p>

<p align="center">
  <img src="_static/screenshots/terminal.png"
       alt="A Picklock session: attaching to a process, scanning for a value, and writing to it"
       width="780" />
</p>

Picklock is a terminal client for
[PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor). It puts the
Cheat Engine workflow — scan, refine, write, follow a pointer chain — behind a
shell modelled on the `mysql` client: ASCII tables, a row count and a timing on
every result, and nothing else competing for your attention.

It exists because the library is a fine tool for a script you have already
written and a poor one for the ten minutes before you write it, when you are
still finding out what is in the process. That part wants a prompt.

```
pip install picklock
picklock
```

Start with the [Quick start](quickstart.md) for the five-minute version, then
the [User guide](guide/index.md) for the workflows. Every command's arguments
are in the [Command reference](reference/commands.md), which is generated from
the code and so cannot drift from what `help` prints at the prompt.

```{admonition} Enjoying Picklock?
:class: tip

If it saved you an afternoon, please **[⭐ star it on GitHub](https://github.com/JeanExtreme002/Picklock)** —
it is the easiest way to support the work and to help other people find it.
And star [PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor)
too: it is what makes any of this work on three operating systems at once.
```

## What you get

<table class="feature-grid">
<tr>
<td width="50%" valign="top">

**A prompt, not a flag soup**

40 commands under six namespaces. Type `scan` to see the scanning ones, `help
scan:value` to see one command's arguments. History, completion and aliases
come with the shell.

**The whole scan cycle**

Every comparison the library exposes, as flags: `--eq`, `--gt`, `--between`,
plus the refine-only `--changed`, `--increased`, `--decreased` for when you
cannot see the number you are hunting.

**Addresses as expressions**

`[[game.exe+0x1a2b3c]+0x10]+0x8` is one argument. So is `#3`, meaning row 3 of
the last scan.

</td>
<td width="50%" valign="top">

**Pointer chains that survive a restart**

`pointer:scan` finds the static paths reaching an address; `pointer:save`,
`pointer:rescan` and `pointer:diff` are the workflow that tells a real path
from a coincidence.

**Scriptable**

The same vocabulary runs non-interactively: `picklock -p 4242 -e "..."`, a file
of commands, or a pipe. Colour off when the output is not a terminal, non-zero
exit on failure.

**One dependency**

PyMemoryEditor, and the standard library. It installs on a bare server as
readily as on a desktop.

</td>
</tr>
</table>

```{toctree}
:hidden:
:caption: Getting started

installation
quickstart
```

<!-- The guide's own pages are listed by guide/index, so they appear once and
     nest under it in the sidebar rather than being claimed by two toctrees. -->
```{toctree}
:hidden:
:caption: User guide

guide/index
```

```{toctree}
:hidden:
:caption: Reference

reference/commands
permissions
troubleshooting
```

```{toctree}
:hidden:
:caption: Project

contributing
security
license
```
