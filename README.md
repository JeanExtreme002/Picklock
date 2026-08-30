# Picklock

A terminal client for [PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor).
Read, write and scan the memory of a running process from any shell, on Windows,
Linux and macOS.

```
pip install picklock
picklock
```

<p align="center">
  <img src="https://raw.githubusercontent.com/JeanExtreme002/Picklock/main/assets/screenshots/terminal.png"
       alt="A Picklock session: attaching to a process, scanning for a value, and writing to it"
       width="780" />
</p>

<p align="center">
  One dependency, pure Python, so it installs on a bare server as readily as on a desktop.
</p>

## Documentation

Full documentation lives at **[picklock.readthedocs.io](https://picklock.readthedocs.io)** —
the scan cycle, address expressions, pointer chains, scripting, platform
permissions, and every command's arguments.

<table>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/quickstart.html"><b>Quick start</b></a></td><td>Attach to a process, find a value, change it.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/guide/scanning.html"><b>Scanning</b></a></td><td>The first-scan/refine cycle, AOB and regex scans.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/guide/addresses.html"><b>Addresses</b></a></td><td><code>module+offset</code>, dereferences, and <code>#N</code> scan rows.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/guide/reading-writing.html"><b>Reading and writing</b></a></td><td>Value types, typed reads and writes, hex views and watches.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/guide/pointers.html"><b>Pointers</b></a></td><td>Pointer scans, and the workflow that makes a path survive a restart.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/guide/scripting.html"><b>Scripting</b></a></td><td>Non-interactive use, exit codes, JSON export.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/reference/commands.html"><b>Command reference</b></a></td><td>Every command and flag, generated from the code.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/permissions.html"><b>Permissions</b></a></td><td>What each OS wants before it lets you attach.</td></tr>
<tr><td><a href="https://picklock.readthedocs.io/en/latest/troubleshooting.html"><b>Troubleshooting</b></a></td><td>Scans that find nothing, chains that stop working.</td></tr>
</table>

The same help is at the prompt: `help` lists the namespaces, typing a namespace
lists its commands, and `help <command>` prints one command's arguments —
generated from the parser that runs it, so the two cannot disagree.

## Development

```
git clone https://github.com/JeanExtreme002/Picklock
cd Picklock
make install-dev
make pre-commit        # lint, type-check, tests
```

Every command is covered end-to-end against a real process — the test process
itself, so the suite needs no privileges and no second program to launch. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Related

Every read, write, scan and pointer walk is performed by
[PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor), the
cross-platform memory library Picklock is built on. If you find Picklock
useful, star that one too — it is what makes any of this work on three
operating systems at once.
