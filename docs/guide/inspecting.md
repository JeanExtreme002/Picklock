# Inspecting a target

What is mapped, what is loaded, what is running. These are the commands you
reach for before a scan — to know where to look — and after one, to understand
what you found.

## Regions

```
memory:regions [--writable] [--executable] [--shared] [--path TEXT] [--at ADDRESS]
```

The target's memory map, re-read on every call so it reflects allocations made
since the last look:

```
picklock [game.exe:41902]> memory:regions --writable
```

The `PERMS` column reads like `/proc/<pid>/maps`: `rwx`, plus `s` for a
shared or file-backed mapping and `p` for a private one.

`--at ADDRESS` answers the question you actually have most often — *what is
this address part of?* — by showing the one region containing it.

### Accessible and reserved

The footer separates two numbers that are easy to confuse:

- **Accessible** — regions that are readable, writable or executable. This is
  memory you can actually touch, and it is the number other tools usually mean
  by "memory used".
- **Reserved** — address space the target has claimed without backing it. On
  macOS in particular this is routinely hundreds of gigabytes, one enormous
  anonymous range that nothing will ever read.

Adding them together produces a number that looks alarming and means nothing,
which is why they are reported apart.

## Modules

```
memory:modules [pattern]
```

The main executable and every shared library (`.dll`, `.so`, `.dylib`), with
the base address each is loaded at.

Two reasons to run it:

1. A module's base moves on every launch under ASLR, so `module+offset` is how
   an address is written down — see [Addresses](addresses.md).
2. Running it **refreshes the module table the address parser uses**, which you
   need after the target loads a library it did not have when you attached.

## Threads

```
ps:threads
```

This is the one command on this page from the `ps:` namespace rather than
`memory:`, because a thread is not memory: it has an id, a state and a
priority, and no address.

`STATE` and `PRIORITY` are filled in only where the platform exposes them
cheaply — Linux does; Windows and macOS leave them empty.

```{admonition} What a TID is depends on the platform
:class: note

Only two of the three are a property of the thread itself:

- **Linux** — the POSIX task id, the same number everything else reports.
- **Windows** — the kernel thread id, likewise.
- **macOS** — a Mach port name, which means something only to the process that
  asked for it.

That last one is a trap worth knowing about: on macOS two tools looking at the
same process get different numbers for the same threads, and neither is wrong.
It is a handle, not a name. Do not carry it between tools, and do not expect it
to match Activity Monitor.
```
