# Quick start

The shortest useful session: find a process, find a value in it, change the
value. Five minutes, and the same five minutes on all three operating systems.

## 1. Open the shell

```bash
picklock
```

```
Welcome to Picklock 0.2.0, a terminal client for PyMemoryEditor.
Type 'help' for the command list, or 'help scanning' for a walkthrough.

picklock>
```

When you do not know what to type, type `help`. It lists the namespaces —
`ps`, `memory`, `scan` and so on. `help scan` lists the commands in one of
them, and `help scan:value` says what that one command takes.

## 2. Find the process

```
picklock> ps:list game
+-------+-------------------+
| PID   | NAME              |
+-------+-------------------+
| 42117 | game-launcher.exe |
| 41902 | game.exe          |
| 43004 | gamehelper.exe    |
| 42130 | GameOverlayUI.exe |
+-------+-------------------+
4 rows in set (0.01 sec)
```

`ps:list` matches a substring, case-insensitively, so `game` finds all four —
the game, its launcher, and two helpers that came along with it. Rows are
sorted by name; `--pid-sort` sorts by PID instead, lowest first, which is
usually — though not guaranteed — oldest first.

Now attach. A PID is unambiguous, and here it has to be: `ps:open game` would
match four processes and Picklock would refuse rather than guess.

```
picklock> ps:open 41902
Attached to game.exe (PID 41902, 64-bit). (0.00 sec)

picklock [game.exe:41902]>
```

The prompt now carries the target. It is there so that a write goes where you
think it goes.

```{admonition} Refused?
:class: note

`ps:open` failing is normal on a first try, and it is about privileges rather
than about Picklock. See [Permissions](permissions.md).
```

## 3. Scan for a value

You know the number on screen — say 100 health — but not where it lives. Scan
for it:

```
picklock [game.exe:41902]> scan:value int32 100 --writable
Showing 20 of 3184 rows — page 1 of 160 — writable regions only (1.42 sec)
Next page: scan:results --page 2
```

3184 addresses hold 100 right now. That is expected: a first scan narrows the
field, it does not identify anything. `--writable` restricts the search to
writable regions, which is where a value that changes almost always lives, and
is much faster.

## 4. Refine

Make the value change in the target — take some damage — and say what it is
now:

```
picklock [game.exe:41902]> scan:next 95
+-----+--------------------+-------+
| ROW | ADDRESS            | VALUE |
+-----+--------------------+-------+
|  #1 | 0x00000201A4C0F118 | 95    |
|  #2 | 0x00000201A51E7740 | 95    |
+-----+--------------------+-------+
2 rows in set (0.02 sec)
```

Repeat until a handful of rows remain. When you *cannot* see the number — a
health bar with no digits — compare against the previous reading instead:

```
picklock [game.exe:41902]> scan:next --decreased
+-----+--------------------+-------+
| ROW | ADDRESS            | VALUE |
+-----+--------------------+-------+
|  #1 | 0x00000201A4C0F118 | 80    |
+-----+--------------------+-------+
1 row in set (0.01 sec)
```

[Scanning](guide/scanning.md) covers the full cycle and every comparison.

## 5. Write

Rows are addressable by number, so you never copy an address by hand:

```
picklock [game.exe:41902]> memory:write #1 int32 9999
Wrote 4 byte(s) to 0x00000201A4C0F118. (0.00 sec)
```

`#1` is read and written with the type the scan that found it used, so a byte
you scanned for does not come back as a four-byte number.

To watch it instead of writing it, `memory:watch #1` redraws the value until
you press ENTER.

## 6. Make it survive a restart

The address you just found is good for this run of the target only. Next launch
it will be somewhere else. What survives is the *path* to it:

```
picklock [game.exe:41902]> pointer:scan #1
picklock [game.exe:41902]> pointer:save health.json
```

Restart the target, attach again, find the value once more, and
`pointer:rescan #1 health.json` keeps only the paths that still land on it.
[Pointers](guide/pointers.md) walks through it.

## Where to go next

- [Scanning](guide/scanning.md) — the refine cycle, AOB and regex scans.
- [Addresses](guide/addresses.md) — `module+offset`, dereferences, `#N`.
- [Reading and writing](guide/reading-writing.md) — types, hex views, watches.
- [Command reference](reference/commands.md) — every command and flag.
