# Pointers

An address found by scanning is good for one run of the target. Next launch,
ASLR and a different allocation order put the value somewhere else. What
survives is the *path* to it: a static address inside a module, plus a series of
offsets to follow.

## Reading a chain you already know

If you have the chain — from a forum post, from a previous session, from a
disassembler — you do not need a pointer scan at all:

```
pointer:read game.exe+0x1a2b3c 0x10 0x8 --type float
pointer:deref game.exe+0x1a2b3c 0x10 0x8
```

`pointer:read` follows the links and reads the value at the end;
`pointer:deref` shows each link along the way, which is what you want when the
chain has stopped working and you need to see where.

`pointer:read --write VALUE` writes at the end of the chain instead of reading.

The same walk is available inside any address expression, so these two are the
same thing:

```
pointer:read game.exe+0x1a2b3c 0x10 0x8
memory:read [[game.exe+0x1a2b3c]+0x10]+0x8
```

See [Addresses](addresses.md#dereferences).

## Finding a chain

```
pointer:scan <address> [--depth N] [--max-offset N] [--max N] [--unaligned] [--all-regions]
```

`pointer:scan` builds a map of every pointer in the target and walks it
backwards from your address until it reaches a static base inside a module:

```
picklock [game.exe:41902]> pointer:scan #1
```

This is the expensive command in Picklock — minutes and hundreds of megabytes
on a large target. Two knobs control the cost:

- `--depth N` — how many links a chain may have (default 3). Each extra level
  costs a lot of time and memory.
- `--max-offset N` — the largest offset to consider (default 1024). Bigger
  means more paths found and much more work.

Ctrl+C stops it and keeps the paths found so far.

`pointer:paths` lists what it found, with the usual paging flags.

## Telling a real path from a coincidence

A pointer scan finds paths that reach the address *right now*. Most of them are
accidents: a number that happens to be that address, in a structure that has
nothing to do with your value. The workflow that separates them is a restart.

```
1. pointer:scan #1                     find candidate paths
2. pointer:save health.json            write them out
3. (restart the target, attach, scan for the value again)
4. pointer:rescan #1 health.json       keep the ones that still land on it
```

Step 4 is the whole point. A path that still reaches the value after a restart
describes the *structure*; one that does not described that one run.

`pointer:rescan` without a file rescans the paths currently held.

## Intersecting several runs

One restart eliminates most accidents. Two or three eliminate nearly all of
them:

```
pointer:diff run1.json run2.json run3.json
```

`pointer:diff` keeps only the paths present in *every* file, compared by their
portable recipe — module, module offset, offsets — rather than by absolute
address, which is the only comparison that means anything across runs. The
result replaces the paths currently held, so `pointer:save` can write it
straight back out.

Two or three runs of the same target usually leave a handful of paths standing,
and those are the ones worth writing into a script.

## Saving and loading

```
pointer:save health.json     write the current paths
pointer:load health.json     read them back
```

The file is JSON, and it stores the portable recipe rather than the addresses,
which is what lets `pointer:rescan` and `pointer:diff` compare across runs.
