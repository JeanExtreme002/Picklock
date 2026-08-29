# Peekmem

A **terminal client for [PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor)** — read, write and scan the memory of a running process from any shell, on any machine, over any SSH session.

---

<p align="center">
  <b>Cheat Engine workflows, typed instead of clicked.</b><br>
  <i>One <code>pip install</code>. No GUI toolkit. No X server. No compiler.</i>
</p>

<p align="center">
  Runs on <b>🪟 Windows</b> · <b>🐧 Linux</b> · <b>🍎 macOS</b> — desktops, servers and containers alike.
</p>

<p align="center">
  <a href="https://github.com/JeanExtreme002/Peekmem/actions/workflows/python-package.yml"><img src="https://github.com/JeanExtreme002/Peekmem/actions/workflows/python-package.yml/badge.svg" alt="Python Package" /></a>
  <a href="https://pypi.org/project/peekmem/"><img src="https://img.shields.io/pypi/v/peekmem" alt="PyPI" /></a>
  <a href="https://github.com/JeanExtreme002/Peekmem/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/peekmem" alt="License" /></a>
  <a href="https://github.com/JeanExtreme002/Peekmem"><img src="https://img.shields.io/badge/python-3.10+-8A2BE2" alt="Python Version" /></a>
  <a href="https://codecov.io/gh/JeanExtreme002/Peekmem"><img src="https://codecov.io/gh/JeanExtreme002/Peekmem/branch/main/graph/badge.svg" alt="Coverage" /></a>
  <a href="https://pypi.org/project/peekmem/"><img src="https://static.pepy.tech/personalized-badge/peekmem?period=total&units=international_system&left_color=grey&right_color=orange&left_text=Downloads" alt="Downloads" /></a>
</p>

---

## Install

```bash
pip install peekmem
peekmem
```

That is the whole setup. Peekmem's only dependency is PyMemoryEditor, which is
pure Python — so it installs on a bare server with no wheels to build, no Qt,
and no display.

For faster scans on large targets, add the `speed` extra. It pulls in NumPy,
which PyMemoryEditor picks up automatically to vectorise the scan loop:

```bash
pip install "peekmem[speed]"
```

## A session

```console
$ peekmem
Welcome to Peekmem 0.1.0, a terminal client for PyMemoryEditor 2.2.0.
Type 'help' for the command list, or 'help scanning' for a walkthrough.

peekmem> ps:list game
+-------+----------+
| PID   | NAME     |
+-------+----------+
| 41902 | game.exe |
+-------+----------+
1 row in set (0.01 sec)

peekmem> ps:open 41902
Attached to game.exe (PID 41902, 64-bit). (0.00 sec)

peekmem [game.exe:41902]> scan:value int32 100 --writable
Showing 20 of 3184 rows (1.42 sec)

peekmem [game.exe:41902]> scan:next 95
+-----+--------------------+-------+
| ROW | ADDRESS            | VALUE |
+-----+--------------------+-------+
|  #1 | 0x00000201A4C0F118 | 95    |
|  #2 | 0x00000201A51E7740 | 95    |
+-----+--------------------+-------+
2 rows in set (0.02 sec)

peekmem [game.exe:41902]> scan:next decreased
+-----+--------------------+-------+
| ROW | ADDRESS            | VALUE |
+-----+--------------------+-------+
|  #1 | 0x00000201A4C0F118 | 80    |
+-----+--------------------+-------+
1 row in set (0.01 sec)

peekmem [game.exe:41902]> memory:write #1 int32 9999
Wrote 4 byte(s) to 0x00000201A4C0F118. (0.00 sec)
```

Found the address, but it moves every launch? Find the pointer path to it, and
keep it:

```console
peekmem [game.exe:41902]> pointer:scan #1 --depth 3 --max 100
+-----+------------------+-------------+--------------------+
| ROW | BASE             | OFFSETS     | TARGET             |
+-----+------------------+-------------+--------------------+
|  #1 | game.exe+0x3BA228 | 0x3E8      | 0x00000201A4C0F118 |
|  #2 | game.exe+0x3B9B70 | 0x310 0x168 | 0x00000201A4C0F118 |
+-----+------------------+-------------+--------------------+
2 rows in set (6.18 sec)

peekmem [game.exe:41902]> pointer:save health.json
Saved 2 path(s) to health.json.

# ... restart the target, find the value again, then:
peekmem [game.exe:52771]> pointer:rescan #1 health.json
1 path(s) still reach 0x000001F73C20E118. (0.03 sec)

peekmem [game.exe:52771]> pointer:read game.exe+0x3BA228 0x3E8 --write 9999
Wrote 4 byte(s) to 0x000001F73C20E118. (0.00 sec)
```

## Scriptable, too

The same vocabulary works non-interactively, which is the point of a CLI on a
server:

```bash
peekmem ps:list chrome                               # one command, then exit
peekmem -p 4242 -e "memory:read game.exe+0x1234"     # attach, read, exit
peekmem -p 4242 -e "scan:value int32 100" -e "scan:results"  # several, in order
peekmem -f setup.peek                               # a file of commands
echo "ps:list" | peekmem                             # a pipe
```

Results go to stdout and errors to stderr, tables are plain ASCII, colour is
off whenever the output is not a terminal, and a failing command exits
non-zero — so `peekmem -e ... | grep`, `>> log.txt` and `&& deploy` all behave.

## What it can do

The help is layered. `help` shows four namespaces and the handful of commands
that drive the shell — not a wall of forty. Each namespace then documents
itself: a usage line, a worked example, and its commands with the arguments
they take.

```console
peekmem> scan:help
usage: scan[:COMMAND]

Search memory for a value, then narrow what you found.

Example:

    peekmem> scan:value int32 100 --writable
    Showing 20 of 3184 rows (1.42 sec)

    peekmem> scan:next 95
    +-----+--------------------+-------+
    | ROW | ADDRESS            | VALUE |
    +-----+--------------------+-------+
    |  #1 | 0x00000201A4C0F118 | 95    |
    +-----+--------------------+-------+
    1 row in set (0.02 sec)

scan commands: (get help with scan:help SUBCOMMAND)

    scan:aob <pattern> [--max N]                 Scan for a byte pattern with wildcards (AOB).
    scan:drop <row> [row ...]                    Remove the named result rows.
    scan:keep <row> [row ...]                    Keep only the named result rows.
    scan:next [op] [value ...]                   Narrow the results with another comparison.
    scan:regex <pattern> [--length N] [--max N]  Scan for text matching a regular expression.
    scan:reset                                   Discard the current scan results.
    scan:results [--limit N] [--offset N]...     Show the current result set, re-read.
    scan:value <type> [value] [--op OP]...       Search the whole address space for a value.
```

`scan:help aob` describes one command. Names go two levels at most, so there
is never a third listing to walk.

A namespace is never a command: typing `scan` prints its page and runs
nothing, whichever way you ask — `scan`, `scan --help`, `scan:help` and
`help scan` all produce the same output.

| Namespace | Commands |
| --- | --- |
| **`ps:`** | `list` · `open` · `close` · `info` |
| **`memory:`** | `read` · `write` · `dump` · `watch` · `regions` · `modules` · `threads` · `alloc` · `free` |
| **`scan:`** | `value` · `next` · `aob` · `regex` · `results` · `keep` · `drop` · `reset` |
| **`pointer:`** | `deref` · `read` · `scan` · `rescan` · `paths` · `save` · `load` · `diff` |
| Top level | `help` · `config` · `source` · `version` · `clear` · `exit` |

`help <command>` — or `<command> --help` — documents each one in full: every
argument, every flag, and examples. That list is generated from the command's
own parser, so it is always exactly what the command accepts:

```console
peekmem> help dump
dump — Hex-dump a range of memory.

Usage: dump <address> [length] [--width N]
Aliases: hexdump, x

Arguments:
  address   address expression: a literal, module+offset, [pointer] or #N —
            see 'help address'
  [length]  number of bytes to read (default 256); hex accepted

Options:
  --width N  bytes per line, overriding the 'dump_width' setting
```

`help types`, `help address` and `help scanning` cover what several commands
share.

Highlights:

- **Every scan comparison PyMemoryEditor exposes** — exact, not-equal, greater,
  smaller, and ranges — plus the refine-only ones that need no value at all:
  `scan:next changed`, `scan:next unchanged`, `scan:next increased`,
  `scan:next decreased`, `scan:next increased-by N`.
- **AOB and regex scans.** `scan:aob "48 8B ? ? 00"` finds a signature
  with wildcards; `scan:regex "Player[0-9]+"` finds text.
- **Thirteen value types** — `int8` … `int64`, `uint8` … `uint64`, `float`,
  `double`, `bool`, `string`, `bytes` — with the aliases you would expect
  (`dword`, `qword`, `short`, `f32`).
- **Pointer scanning and the full rescan workflow**, so an address survives a
  restart.
- **`memory:watch`**, which turns a terminal into a live cheat table:
  `memory:watch game.exe+0x1234 int32` prints a line every time the value
  changes.
- **Progress you can trust.** Long scans report a percentage that advances
  whether or not anything is being found, and Ctrl+C stops a scan while keeping
  what it already found.
- **Every listing pages the same way.** `--limit`, `--offset` and `--all` on
  each of them, and a truncated table ends with the command that shows the
  next page — `Next page: memory:regions --offset 20` — so it is a copy-paste,
  not a puzzle.
- **Ctrl+C means the obvious thing.** During a command it abandons that command
  and returns to the prompt; at the prompt it quits. So stopping a scan costs
  one keystroke and leaving costs two, and neither one loses your results by
  surprise. Ctrl+D and `exit` quit too.

### Addresses are expressions

Anywhere an address is taken:

```
0x7ffee3a01000          a literal (decimal works too)
game.exe+0x1234         a module base plus a static offset — survives ASLR
[game.exe+0x1234]+0x10  dereference, then add
[[base+0x8]+0x20]+0x4   nested as deeply as you like
#3                      the address on row 3 of the last scan
```

So the whole chain fits on one line:
`memory:read [[game.exe+0x1a2b3c]+0x10]+0x8 float`.

## Permissions

Reading another process's memory is a privileged operation everywhere:

- **Windows** — run your terminal as Administrator to touch processes you do
  not own.
- **Linux** — `sudo peekmem`, or grant the capability once with
  `sudo setcap cap_sys_ptrace+ep $(readlink -f $(which python3))`. Some
  distributions also need `/proc/sys/kernel/yama/ptrace_scope` set to `0`.
- **macOS** — SIP blocks reading most processes. `sudo peekmem` works for
  processes you own; anything else needs a signed binary carrying the debugger
  entitlement.

Peekmem says which of these applies when an `open` is refused.

## Peekmem vs. the PyMemoryEditor app

They are different front ends to the same library, and installing one does not
install the other:

|  | **Peekmem** | **PyMemoryEditor's app** |
| --- | --- | --- |
| Interface | terminal, ASCII | desktop GUI (Qt) |
| Install | `pip install peekmem` | `pip install "PyMemoryEditor[app]"` |
| Needs a display | no | yes |
| Scriptable | yes — `-e`, `-f`, pipes | no |
| Good for | servers, SSH, CI, automation | interactive exploration on a desktop |

## Related

Peekmem is a client. Every read, write, scan and pointer walk is performed by
**[PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor)** — the
cross-platform memory library it is built on.

⭐ **If Peekmem is useful to you, star the repo — and
[star PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor) too.**
It is the engine underneath, and it is what makes any of this work on three
operating systems at once.

## Contributing

Issues and pull requests are welcome.

```bash
git clone https://github.com/JeanExtreme002/Peekmem
cd Peekmem
make install-dev      # pip install -e ".[dev]"
make pre-commit       # lint + type-check + tests
```

`make help` lists every target. The test suite never attaches to another
process, so it runs anywhere — including CI runners that would refuse.

[**CONTRIBUTING.md**](CONTRIBUTING.md) covers the project layout, the two rules
that keep its shape, and how to add a command (it is one decorator, and `help`
plus the tests come along for free).

- 🐛 [Report a bug](https://github.com/JeanExtreme002/Peekmem/issues/new?template=bug_report.md)
- 💡 [Request a feature](https://github.com/JeanExtreme002/Peekmem/issues/new?template=feature_request.md)
- 🔒 [Security policy](SECURITY.md) — please do **not** open a public issue
- 🤝 [Code of Conduct](CODE_OF_CONDUCT.md)

## License

MIT — see [LICENSE](LICENSE).
