# Troubleshooting

## `ps:open` is refused

The most common first experience, and almost always about privileges rather
than about Picklock. See [Permissions](permissions.md) — the short version is
`sudo` on Linux and macOS, Administrator on Windows, and on macOS possibly
nothing at all for a process you did not start.

## A scan finds nothing

Work through these in order:

1. **Wrong type.** A value shown as `100` might be an `int32`, a `float`, a
   `double` or a `string`. Health and ammo are usually integers; positions and
   percentages are usually floats. Try `float` when `int32` finds nothing.
2. **Wrong value.** What the screen shows is not always what is stored — a bar
   at "75%" may hold `0.75`, or `75.0`, or `7500`. Scan with a comparison
   instead: `scan:value float --between 0.7 0.8`.
3. **`--writable` excluded it.** A value that never changes may live in
   read-only data. `--all-regions` searches everything. Picklock says so when
   a result set skipped read-only memory, so check the footer under the table
   for "writable regions only" — and remember the `writable_only` setting
   produces it too.
4. **It moved.** Between your first scan and your refine, the target may have
   reallocated. Start over with `scan:reset`.

## A scan finds far too much

That is normal for a first scan — thousands of hits is the expected outcome,
not a failure. What identifies the address is the *refine*: change the value in
the target and run `scan:next`. See [Scanning](guide/scanning.md).

If the first scan is so large it is slow to work with, `--writable` and
`--max N` both cut it down.

## The scan hit the results cap

`max_results` (default 1,000,000) is the ceiling on how many hits are kept.
Hitting it means the scan was too loose to be useful — narrow it with a
comparison or with `--writable` rather than raising the cap.

## `memory:read` gives a number I do not recognise

Two usual causes:

- **Width.** Reading a byte as `int32` pulls in the three bytes after it. A
  `#N` row avoids this — it is read with the type the scan that found it used.
- **Signedness.** `int8` reads `0xFF` as `-1`; `uint8` reads it as `255`.

## A pointer chain stopped working

Expected, if it was never verified. A chain found by one `pointer:scan` reaches
the address in *that run* and is very often a coincidence. Verify it across a
restart with `pointer:rescan`, and across two or three with `pointer:diff` —
see [Pointers](guide/pointers.md).

`pointer:deref` shows each link, so you can see which one stopped resolving.

## `memory:watch` shows one line and then nothing

That is the design: only samples whose value *changed* are printed, so a still
value prints once. `--all` prints every sample, which is how you tell a still
value apart from a watch that has stopped.

Press ENTER to stop a watch.

## `memory:regions` reports far more memory than Activity Monitor

The footer separates **accessible** from **reserved**. Reserved is address
space claimed without being backed by memory — on macOS routinely hundreds of
gigabytes in one anonymous range. Other tools report the accessible figure. See
[Inspecting a target](guide/inspecting.md#accessible-and-reserved).

## Thread IDs do not match another tool (macOS)

They are not supposed to. On macOS a TID is a Mach port name — a handle that
means something only to the process that asked for it. Two tools looking at the
same process get different numbers, and neither is wrong. See
[Inspecting a target](guide/inspecting.md#threads).

## Colour codes in a log file

They should not be there — Picklock drops colour when stdout is not a terminal.
If something in between is pretending to be one, `--no-color` or `NO_COLOR=1`
settles it.

## Scans are slow

```bash
pip install "picklock[speed]"
```

NumPy lights up a vectorised comparison path inside PyMemoryEditor. Picklock
needs no change to use it. Beyond that, `--writable` is the big one: it is
usually a tenth of the address space, and where a changing value lives anyway.

## Picklock will not start

If it reports a PyMemoryEditor version that is too old, upgrade it:

```bash
pip install --upgrade PyMemoryEditor
```

Picklock checks at startup because the alternative is a confusing failure deep
inside a scan.

## Something else

Please [open an issue](https://github.com/JeanExtreme002/Picklock/issues) with
your OS, your Python version, the output of `picklock --version`, and the
command that misbehaved.
