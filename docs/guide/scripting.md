# Scripting

Picklock is a shell first, but the same vocabulary runs non-interactively. The
commands are the same, the output is the same minus the colour, and the exit
status means what you would expect.

## One command

```bash
picklock ps:list chrome
```

The first positional argument is a command line. It runs, prints, and exits.

## Attaching from the command line

```bash
picklock -p 4242 -e "memory:read game.exe+0x1234 int32"
picklock -n game.exe -e "scan:value int32 100 --writable" -e "scan:results"
```

- `-p / --pid` and `-n / --name` attach before anything runs.
- `-i / --ignore-case` and `--partial` apply to `--name`.
- `-e / --execute` is repeatable and runs in order.

A failing command stops the run and exits non-zero, so a chain does not
carry on against a target it never attached to.

## A file of commands

```bash
picklock -f setup.txt
```

```
# setup.txt — comments and blank lines are ignored
ps:open game.exe
config:set writable_only on
scan:value int32 100
```

The same file can be run from inside the shell with `source setup.txt`,
which is the usual way to keep a scan you repeat.

## A pipe

```bash
echo "ps:list" | picklock
printf 'ps:open game.exe\nmemory:read game.exe+0x1234\n' | picklock
```

Reading from a pipe runs each line as a command. The banner is suppressed
automatically when stdin is not a terminal; `-q / --quiet` suppresses it
otherwise.

## Output that behaves

- Results on **stdout**, errors on **stderr**, so `2>/dev/null` and `| grep`
  both do what you mean.
- **Colour off** whenever stdout is not a terminal, and `--no-color` or
  `NO_COLOR` turns it off regardless.
- `--no-timing` drops the `(0.01 sec)` footer, which is the one part of the
  output that changes between identical runs — worth setting when you are
  diffing.
- **Non-zero exit** on failure.

Put together:

```bash
picklock -p 4242 --no-color --no-timing -e "scan:results --all" > hits.txt \
  && echo "scan finished"
```

## Structured output

For anything you intend to parse, prefer the export over the table:

```bash
picklock -p 4242 -e "scan:value int32 100" -e "scan:results --export hits.json"
```

The table is designed to be read by a person and its column widths depend on
the data. `--export` writes every result as JSON, not the page on screen.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | everything ran |
| 1 | a command failed — the error is on stderr |
| 2 | the command line itself was wrong |
| 130 | interrupted with Ctrl+C |
