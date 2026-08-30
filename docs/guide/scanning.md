# Scanning

Scanning is how you find an address when all you know is a number on a screen.
The shape of it is always the same: cast a wide net, change the value, narrow.

## The cycle

```
1. scan:value int32 100     every address holding 100 right now
2. (make the value change in the target)
3. scan:next 95             of those, the ones now holding 95
```

Step 3 repeats until a handful of rows remain. A first scan is *supposed* to
return thousands of rows — the number 100 is everywhere in a running program.
What identifies the address is not the value, it is the value changing the way
the thing on your screen changed.

```
picklock [game.exe:41902]> scan:value int32 100 --writable
Showing 20 of 3184 rows — page 1 of 160 (1.42 sec)

picklock [game.exe:41902]> scan:next 95
2 rows in set (0.02 sec)
```

`--writable` is worth reaching for by default: a value that changes lives in
writable memory, and skipping everything else makes the scan several times
faster. `--all-regions` overrides it when you are looking for something in
read-only data.

Because that restriction is easy to forget and expensive to forget, a
result set that skipped read-only memory says so — on the scan, on every
refine, and again on `scan:results`:

```
Note: Writable regions only — nothing in read-only memory was searched.
Use '--all-regions' on the first scan to include it.
```

You will also see it without having typed `--writable`, if the
`writable_only` setting is on. That is the point of the line: the reason an
address is missing should not be a setting you turned on last week.

## When you cannot see the number

A health bar with no digits, a timer that only moves — you cannot type the new
value because you do not know it. Compare against the previous reading instead:

```
scan:next --changed          different from last time
scan:next --unchanged        the same as last time
scan:next --increased        went up
scan:next --decreased        went down
scan:next --increased-by 5   went up by exactly 5
scan:next --decreased-by 5   went down by exactly 5
```

Alternate `--unchanged` (while nothing is happening) with `--decreased` (after
taking damage) and a bar with no numbers narrows just as fast as one with them.

## Comparisons are flags

Every comparison is a flag, never a bare word:

```
scan:value int32 --gt 50            greater than
scan:value int32 --between 10 20    inside a range, inclusive
scan:next --not-between 10 20       outside it
scan:next --ne 0                    anything but zero
```

The value slot only ever holds a value. That is the reason: `scan:next changed`
searches for the *word* "changed", which is a perfectly reasonable thing to
want when you are scanning text, and `--changed` is the comparison. Giving a
value on its own is the same as `--eq`, so `scan:next 95` and
`scan:next --eq 95` are one command.

## Looking at where you are

A scan prints its first page. `scan:results` is how you reach the rest, and how
you see the current state between rounds:

```
scan:results              the first page, re-read
scan:results --page 2     the next one          (-p)
scan:results --all        every row             (-a)
scan:results --limit 50   a bigger page         (-l)
```

It re-reads every address, so `VALUE` is what the target holds *now*, not what
the scan found, and `PREVIOUS` is the reading the comparisons above measure
against. Watching those two columns is usually how you spot the real row.

To take the results somewhere else:

```
scan:results --export results.json
```

That writes every result, not the page on screen.

## Saying which rows are real

When you can see which rows matter, say so directly instead of inventing a
comparison that happens to exclude the others:

```
scan:keep 1 4 7-9      keep those rows, drop the rest
scan:drop 2            the other way round
scan:reset             throw the results away and start over
```

Ranges and lists both work. Rows renumber after either command, so `#1` is
always the first surviving row.

## Byte patterns and text

Two scans do not take a value at all.

**AOB** — an array-of-bytes signature, the standard way to find code that moves
between builds. `?` is a wildcard for one byte:

```
scan:aob "48 8B ? ? 00"
```

**Regex** — a search over the target's text:

```
scan:regex "Player[0-9]+"
scan:regex "Player[0-9]+" --length 64
```

Both take `--max N` to stop after N hits, which matters on a large target where
a loose pattern matches a great many times.

## Cost, and stopping

A scan walks the whole address space, so it costs seconds rather than
milliseconds, and a first scan on a multi-gigabyte process costs more than
that. Two things help:

- `--writable` (much less to walk) and `--max N` (stop early).
- `pip install "picklock[speed]"`, which lets PyMemoryEditor vectorise the
  comparison loop with NumPy.

Ctrl+C stops a scan and keeps whatever it found, so an interrupted scan is
still a result set you can refine.

Regions that cannot be read are skipped rather than failing the scan — a
process is a moving target, and a page that vanished mid-scan is normal.

## Then what

An address found by scanning is good for this run of the target only. To keep
it across restarts, find the pointer path that reaches it — see
[Pointers](pointers.md).
