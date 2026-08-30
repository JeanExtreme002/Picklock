# Picklock

A terminal client for [PyMemoryEditor](https://github.com/JeanExtreme002/PyMemoryEditor).
Read, write and scan the memory of a running process from any shell, on Windows,
Linux and macOS.

One dependency, pure Python, so it installs on a bare server as readily as on a desktop.

```
pip install picklock
picklock
```

<p align="center">
  <img src="https://raw.githubusercontent.com/JeanExtreme002/Picklock/main/assets/screenshots/terminal.png"
       alt="A Picklock session: scanning a live process for a value, narrowing it down, and writing to it"
       width="780" />
</p>

<p align="center">
  <i>A real session, captured by <a href="scripts/generate_terminal_image.py">a script that runs the commands</a>
  against a process it stands up for the purpose — no numbers in it were typed by hand.</i>
</p>

## Usage

```
$ picklock
Welcome to Picklock 0.1.0, a terminal client for PyMemoryEditor.
Type 'help' for the command list, or 'help scanning' for a walkthrough.

picklock> ps:list game
+-------+----------+
| PID   | NAME     |
+-------+----------+
| 41902 | game.exe |
+-------+----------+
1 row in set (0.01 sec)

picklock> ps:open 41902
Attached to game.exe (PID 41902, 64-bit). (0.00 sec)

picklock [game.exe:41902]> scan:value int32 100 --writable
Showing 20 of 3184 rows — page 1 of 160 (1.42 sec)
Next page: scan:results --page 2

picklock [game.exe:41902]> scan:next 95
+-----+--------------------+-------+
| ROW | ADDRESS            | VALUE |
+-----+--------------------+-------+
|  #1 | 0x00000201A4C0F118 | 95    |
|  #2 | 0x00000201A51E7740 | 95    |
+-----+--------------------+-------+
2 rows in set (0.02 sec)

picklock [game.exe:41902]> scan:next --decreased
+-----+--------------------+-------+
| ROW | ADDRESS            | VALUE |
+-----+--------------------+-------+
|  #1 | 0x00000201A4C0F118 | 80    |
+-----+--------------------+-------+
1 row in set (0.01 sec)

picklock [game.exe:41902]> memory:write #1 int32 9999
Wrote 4 byte(s) to 0x00000201A4C0F118. (0.00 sec)
```

`help scanning` walks through that cycle, including the comparisons that need
no value at all (`--changed`, `--increased`) for when you cannot see the number
you are looking for.

## Commands

Every command is `namespace:command`. Typing a namespace alone prints its page;
`help <command>` prints one command's arguments, generated from the parser that
runs it, so the two cannot disagree.

| Namespace | Commands |
| --- | --- |
| `ps:` | `list` `open` `close` `info` |
| `memory:` | `read` `write` `hex` `watch` `regions` `modules` `threads` `alloc` `free` |
| `scan:` | `value` `next` `aob` `regex` `results` `keep` `drop` `reset` |
| `pointer:` | `scan` `deref` `read` `rescan` `paths` `save` `load` `diff` |
| `alias:` | `add` `list` `remove` |
| `config:` | `list` `set` `reset` |
| top level | `help` `source` `version` `clear` `exit` |

Notable:

- **Scanning.** Every comparison PyMemoryEditor exposes, as flags: `--eq`,
  `--ne`, `--gt`, `--lt`, `--ge`, `--le`, `--between`, plus the refine-only
  `--changed`, `--unchanged`, `--increased`, `--decreased`, `--increased-by`.
  AOB with wildcards (`scan:aob "48 8B ? ? 00"`) and text regex
  (`scan:regex "Player[0-9]+"`).
- **Pointer chains.** `pointer:scan` finds the static paths that reach an
  address; `pointer:save`, `pointer:rescan` and `pointer:diff` are the workflow
  that separates a path that survives a restart from a coincidence.
- **`memory:watch`** follows one value; **`memory:hex --watch`** redraws a whole
  range in place. Both stop on ENTER.
- **Paging.** `--limit`, `--page`, `--all` on every listing (`-l`, `-p`, `-a`),
  a footer that says where you are, and the command for the next page spelled
  out under it.
- **`scan:results --export results.json`** writes every result, not the page on
  screen.

## Addresses

Anywhere an address is taken:

```
0x7ffee3a01000          a literal; decimal works too
game.exe+0x1234         a module base plus a static offset — survives ASLR
[game.exe+0x1234]+0x10  dereference, then add
[[base+0x8]+0x20]+0x4   nested as deeply as you like
#3                      row 3 of the last scan
```

So a whole chain fits on one line: `memory:read [[game.exe+0x1a2b3c]+0x10]+0x8 float`.

A `#N` row is read with the type the scan that found it used, not a default.

## Scripting

Picklock is a shell first, but the same vocabulary runs non-interactively:

```
picklock ps:list chrome                          # one command, then exit
picklock -p 4242 -e "memory:read game.exe+0x1234"
picklock -p 4242 -e "scan:value int32 100" -e "scan:results"
picklock -f setup.picklock                       # a file of commands
echo "ps:list" | picklock                        # a pipe
```

Results on stdout, errors on stderr, plain ASCII tables, colour off whenever
the output is not a terminal, and a non-zero exit on failure — so
`| grep`, `>> log` and `&& deploy` all behave.

## Permissions

Reading another process's memory is privileged everywhere:

- **Linux** — `sudo picklock`, or grant it once with
  `sudo setcap cap_sys_ptrace+ep $(readlink -f $(which python3))`. Some
  distributions also need `/proc/sys/kernel/yama/ptrace_scope` set to `0`.
- **Windows** — run the terminal as Administrator to touch processes you do not
  own.
- **macOS** — SIP blocks reading most processes. `sudo picklock` works for
  processes you own; anything else needs a binary signed with the debugger
  entitlement.

Picklock names whichever applies when an `ps:open` is refused.

## Files

Aliases and settings persist, in `$XDG_CONFIG_HOME/picklock/` (default
`~/.config/picklock/`, `%APPDATA%\picklock` on Windows) as `aliases.json` and
`settings.json`. `alias:list` and `config:list` print their paths;
`PICKLOCK_CONFIG_DIR` moves both. Only settings you changed are stored, so a
default that moves in a later release still reaches you.

## Development

```
git clone https://github.com/JeanExtreme002/Picklock
cd Picklock
make install-dev
make pre-commit        # lint, type-check, tests
pytest -m "not slow"   # ~2 s, skipping the live scans
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

## License

MIT — see [LICENSE](LICENSE).
