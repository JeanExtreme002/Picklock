# Addresses

Every command that takes an address takes an *expression*, so a pointer chain
is one argument rather than four commands and a notepad.

```
0x7ffee3a01000          a literal; decimal works too
game.exe+0x1234         a module's base plus a static offset
"libfoo-1.so"+0x20      quote a name containing '-' or spaces
[game.exe+0x1234]       the pointer stored there, dereferenced
[[base+0x8]+0x20]+0x4   nested as deeply as you like
#3                      the address on row 3 of the last scan
```

So a whole chain fits on one line:

```
memory:read [[game.exe+0x1a2b3c]+0x10]+0x8 float
```

## `module+offset`

This is the form worth writing down. A module's base address moves on every
launch under ASLR, but the offset inside it does not, so `game.exe+0x1234`
keeps working across restarts where a bare address does not.

Module names are matched case-insensitively, and an unambiguous prefix is
enough — `game` finds `game.exe`. `memory:modules` lists them, and running it
also refreshes the table the address parser uses, which you want after the
target loads a library.

A name containing a hyphen or a space has to be quoted, because otherwise the
hyphen reads as subtraction:

```
memory:read "libssl-3.so"+0x120 int32
```

## Dereferences

Square brackets read the pointer stored at an address and continue from there.
They nest, and arithmetic applies at each level:

```
[game.exe+0x1234]         one link
[[game.exe+0x1234]+0x10]  two
[[base+0x8]+0x20]+0x4     two links, then a field offset
```

This is exactly what a pointer chain is, which is why
[`pointer:read`](#cmd-pointer-read) and a bracketed
expression are two spellings of the same walk. The difference is what happens
when a link is unreadable: the expression fails with the address it could not
follow, so you learn which link broke.

(scan-row-numbers)=
## `#N` — a row from the last scan

After a scan, rows are addressable by number:

```
memory:read #1 int32
memory:write #1 int32 9999
pointer:scan #1
```

Two details worth knowing:

- A `#N` row is read with **the type the scan that found it used**, not a
  default. A byte you scanned for comes back as a byte, not as a four-byte
  number that happens to start with it.
- The numbers renumber after `scan:keep` and `scan:drop`, so `#1` is always the
  first surviving row.

`scan:results` prints the current numbering.
