# Picklock

<p align="center">
  <img src="https://raw.githubusercontent.com/JeanExtreme002/Picklock/main/assets/screenshots/terminal.png"
       alt="A Picklock session: attaching to a process, scanning for a value, and writing to it"
       width="780" />
</p>

<p align="center">
  <b>Read, write and scan the memory of a running process from any terminal.</b><br>
  <i>Pure Python. It installs on a bare server as easily as on a desktop.</i>
</p>

<p align="center">
  <a href="https://github.com/JeanExtreme002/Picklock/actions/workflows/python-package.yml"><img src="https://github.com/JeanExtreme002/Picklock/actions/workflows/python-package.yml/badge.svg" alt="Python Package" /></a>
  <a href="https://pypi.org/project/Picklock/"><img src="https://img.shields.io/pypi/v/Picklock" alt="Pypi" /></a>
  <a href="https://github.com/JeanExtreme002/Picklock"><img src="https://img.shields.io/pypi/l/Picklock" alt="License" /></a>
  <a href="https://github.com/JeanExtreme002/Picklock"><img src="https://img.shields.io/badge/python-3.10+-8A2BE2" alt="Python Version" /></a>
</p>

---

A terminal client for reading, writing and scanning process memory, on Windows,
Linux and macOS.

```
pip install picklock
picklock
```

It uses [PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor) as its only dependency, so it can be used easily anywhere.

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

Use `help` to list Picklock's commands, and `help <command>` to get more details about one command.

## 🤝 Contributing

Pull requests, bug reports and feature ideas are very welcome. Read
[CONTRIBUTING.md](https://github.com/JeanExtreme002/Picklock/blob/main/CONTRIBUTING.md) for the development setup, test layout and
the small set of platform-specific quirks to be aware of.

## ⭐ Related

Every read, write, scan and pointer walk is performed by
[PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor), the
cross-platform memory library Picklock is built on. If you find Picklock
useful, check out that one too — it is what makes any of this work on three
operating systems at once.

## License

Released under the [MIT License](https://github.com/JeanExtreme002/Picklock/blob/main/LICENSE) — free for personal and commercial use.
