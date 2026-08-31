# Reading and writing

## Types

Every read and write is typed. Picklock takes the type as a word, with the
aliases people actually type:

| Type | Bytes | Also | |
| --- | --- | --- | --- |
| `int8` | 1 | `i8`, `char`, `sbyte` | signed |
| `int16` | 2 | `i16`, `short` | signed |
| `int32` | 4 | `i32`, `int` | signed — the usual default |
| `int64` | 8 | `i64`, `long`, `longlong` | signed |
| `uint8` | 1 | `u8`, `byte`, `ubyte` | unsigned |
| `uint16` | 2 | `u16`, `ushort`, `word` | unsigned |
| `uint32` | 4 | `u32`, `uint`, `dword` | unsigned |
| `uint64` | 8 | `u64`, `ulong`, `qword` | unsigned |
| `float` | 4 | `f32`, `single` | IEEE |
| `double` | 8 | `f64` | IEEE |
| `bool` | 1 | `boolean` | |
| `string` | varies | `str`, `utf8`, `text` | UTF-8; give a length |
| `bytes` | varies | `hex`, `bytearray`, `aob` | hex, as `DE AD BE EF` |

`help types` prints the same table at the prompt.

`string` and `bytes` need a length, because there is nothing in memory to say
where they stop:

```
memory:read 0x7ffee3a01000 string 32
```

## Reading

```
memory:read <address> [type] [length] [--count N] [--hex]
```

```
picklock [game.exe:41902]> memory:read game.exe+0x1234 int32
+--------------------+-------+-------+
| ADDRESS            | TYPE  | VALUE |
+--------------------+-------+-------+
| 0x00000201A4C0F118 | int32 | 100   |
+--------------------+-------+-------+
```

`--count N` reads N consecutive values of that type, which is how you look at
an array without working out the stride yourself. `--hex` shows integers in
hex as well as decimal.

Leaving the type off falls back to the `int32` default — or, for a `#N` row, to
the type the scan that found it used. See [Addresses](#scan-row-numbers).

## Writing

```
memory:write <address> <type> <value> [--length N] [--null-terminated]
```

```
picklock [game.exe:41902]> memory:write #1 int32 9999
Wrote 4 byte(s) to 0x00000201A4C0F118. (0.00 sec)
```

The type is required here. That is on purpose: a write is the one operation you
cannot undo by looking again, and inferring a width from the way a number was
typed is how you end up writing four bytes where you meant one.

For text, `--length` pads or truncates to a fixed field and `--null-terminated`
adds the terminator — both matter when you are writing into a buffer that
something else is going to read.

```{admonition} Writes are real
:class: warning

Picklock writes to a live process. There is no undo, `ps:close` does not roll
anything back, and a wrong address can crash the target. On a process you care
about, read first and write second.
```

## Hex

```
memory:hex <address> [length] [--width N] [--watch] [--interval S]
```

The classic three-column view — absolute address, hex bytes, printable ASCII:

```
picklock [game.exe:41902]> memory:hex #1 32
00000201A4C0F118  0F 27 00 00 39 05 00 00 00 00 00 00 00 00 00 00  |.'..9...........|
00000201A4C0F128  00 00 00 00 00 00 00 00 B0 CB 03 02 01 00 00 00  |................|

32 bytes (0.00 sec)
```

Length defaults to 256 bytes. `--width` sets bytes per line, overriding the
`hex_width` setting.

The read is a single call, so a range crossing into an unmapped page fails as a
whole rather than handing back half the bytes and letting you believe the rest.

## Watching

Two commands follow memory as it changes, and both stop when you press ENTER.

```
memory:watch #1 int32       one value, redrawn as it changes
memory:hex #1 64 --watch    a whole range, redrawn in place
```

`memory:watch` is for a single number; `memory:hex --watch` is for a structure,
where seeing which *other* fields move at the same time is the point.

The two differ in how they print. `memory:hex --watch` redraws in place, so
the screen always shows the current bytes. `memory:watch` prints a line per
change — a change log rather than a live figure — which means a value that is
not moving shows one line and then nothing. `--all` prints every sample instead,
which is how you tell a still value apart from a watch that has stopped.

`--interval S` sets the polling period (default from the `watch_interval`
setting) and `--count N` stops after N samples, which is what you want in a
script.

## Allocating

```
memory:alloc <size> [--permission N]
memory:free <address> [size]
```

`memory:alloc` reserves memory *inside the target* and prints the address —
somewhere to put a string or a structure that the target does not already have
room for. `memory:free` gives it back.

These are the sharpest tools here. Freeing something the target is using will
crash it, and Picklock does not track what you allocated.
