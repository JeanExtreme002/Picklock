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
  <a href="https://pypi.org/project/picklock/"><img src="https://img.shields.io/pypi/v/Picklock" alt="Pypi" /></a>
  <a href="https://github.com/JeanExtreme002/Picklock"><img src="https://img.shields.io/pypi/l/Picklock" alt="License" /></a>
  <a href="https://github.com/JeanExtreme002/Picklock"><img src="https://img.shields.io/badge/python-3.10+-8A2BE2" alt="Python Version" /></a>
  <a href="https://pypi.org/project/picklock/"><img src="https://static.pepy.tech/personalized-badge/picklock?period=total&units=international_system&left_color=grey&right_color=orange&left_text=Downloads" alt="Downloads" /></a>
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

Use `help` to list Picklock's commands, and `help <command>` to get more details about one command.

## Contributing

Pull requests, bug reports and feature ideas are very welcome. Read
[CONTRIBUTING.md](https://github.com/JeanExtreme002/Picklock/blob/main/CONTRIBUTING.md) for the development setup, test layout and
the small set of platform-specific quirks to be aware of.

## Related

Every read, write, scan and pointer walk is performed by
[PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor), the
cross-platform memory library Picklock is built on. If you find Picklock
useful, check out that one too — it is what makes any of this work on three
operating systems at once.

## License

Released under the [MIT License](https://github.com/JeanExtreme002/Picklock/blob/main/LICENSE) — free for personal and commercial use.
