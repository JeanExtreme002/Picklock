# Picklock

<p align="center">
  <img src="_static/screenshots/terminal.png"
       alt="A Picklock session: attaching to a process, scanning for a value, and writing to it"
       width="780" />
</p>

<p align="center">
  <b>Read, write and scan the memory of a running process from any terminal.</b><br>
  <i>Pure Python. It installs on a bare server as easily as on a desktop.</i>
</p>

<p align="center">
  <a href="https://github.com/JeanExtreme002/Picklock/actions/workflows/python-package.yml"><img src="https://github.com/JeanExtreme002/Picklock/actions/workflows/python-package.yml/badge.svg" alt="Python Package" /></a>
  <a href="https://pypi.org/project/picklock/"><img src="https://img.shields.io/pypi/v/picklock" alt="Pypi" /></a>
  <a href="https://github.com/JeanExtreme002/Picklock"><img src="https://img.shields.io/pypi/l/picklock" alt="License" /></a>
  <a href="https://github.com/JeanExtreme002/Picklock"><img src="https://img.shields.io/badge/python-3.10+-8A2BE2" alt="Python Version" /></a>
</p>

---

Picklock is a terminal client for
[PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor) to read, write and scan the memory of a running process from any shell, on Windows, Linux and macOS.

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
```

## What you get

<table class="feature-grid">
<tr>
<td width="50%" valign="top">

**A prompt, quick and simple**

Easy commands for quick actions. Type `help` to see all the features. A hex
viewer, history and aliases are all there.

**The whole scan cycle**

Use the `scan` commands to search memory for a value or pattern, then narrow what you found. Every comparison is
exposed as a flag. Look at where you are with `scan:results`.

**Addresses as expressions**

`[[game.exe+0x1a2b3c]+0x10]+0x8` is one argument. So is `#3`, meaning row 3 of
the last scan, instead of passing a full memory address.

</td>
<td width="50%" valign="top">

**Pointer chains that survive a restart**

`pointer:scan` finds the static paths reaching an address; `pointer:save`,
`pointer:rescan` and `pointer:diff` are the workflow that tells a real path
from a coincidence.

**Scriptable**

The same vocabulary runs non-interactively: `picklock -p 4242 -e "..."`, a file
of Picklock commands, or a pipe.

**One dependency**

PyMemoryEditor, and the standard library. It installs easily anywhere.

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
funding
license
```
