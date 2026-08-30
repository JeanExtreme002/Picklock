# Contributing to Picklock

Thanks for your interest in contributing!

Picklock is a terminal client for [PyMemoryEditor][pyme]. If your change is
about *how memory is read, written or scanned*, it probably belongs upstream in
PyMemoryEditor; if it is about *what you type and what you see*, it belongs
here. When in doubt, open an issue and it will be routed.

## Development setup

```bash
python -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
make install-dev            # pip install -e ".[dev]"
```

The `Makefile` is the single source of truth for the dev commands below — run
`make help` to see every target. The raw command each target wraps is shown in
parentheses if you would rather run it directly.

## Running the test suite

```bash
make test                   # pytest tests -v
```

The suite never attaches to a process. It covers parsing, formatting, dispatch
and help — the parts that are Picklock's own — and leaves reading another
process's memory to PyMemoryEditor's tests. That is deliberate: it means the
suite runs identically on any machine, including CI runners where opening a
second process is not permitted.

The consequence is that a change to a command *body* is not covered by the
suite. Exercise it by hand against a real target and say so in the PR — a
transcript of the session is the ideal evidence.

## Linting and type checking

```bash
make lint                   # flake8 picklock tests
make type-check             # mypy picklock
```

## Before you push

```bash
make pre-commit             # lint + type-check + test
```

CI runs the same three, plus a build, on Ubuntu, Windows and macOS across
Python 3.10–3.13. The matrix matters here: the shell has to start and dispatch
identically where `readline` is missing (Windows), and `picklock -e "version"`
is smoke-tested from the installed console script on every cell.

## Project layout

```
picklock/
├── __init__.py        # Version and the public re-exports
├── __main__.py        # python -m picklock
├── cli.py             # argparse front end: flags, batch mode, exit statuses
├── shell.py           # The REPL: line splitting, dispatch, readline, history
├── session.py         # Everything a session remembers: target, results, settings
├── addressing.py      # The address expression language ([...], module+offset, #N)
├── valuetypes.py      # The type vocabulary and the signed/unsigned bridge
├── output.py          # Every byte Picklock prints: tables, hexdump, footers
├── processes.py       # Cross-platform process enumeration
├── store.py           # The JSON files Picklock remembers things in
├── errors.py          # CommandError and friends
└── commands/          # One module per group; each registers with @command
```

Two rules keep the shape:

- **Commands never print directly.** They go through `session.printer`, which
  is what makes output testable against a `StringIO`.
- **Anything the user got wrong raises `CommandError`.** The shell catches that
  one class, prints one `ERROR:` line and returns to the prompt. An exception
  that is *not* a `CommandError` is a bug in Picklock and is allowed to escape
  with its traceback.

## Adding a command

1. Pick the module in `picklock/commands/` that matches the namespace.
2. Register the handler. The name is a colon-separated path whose first
   segment is one of the groups in `NAMESPACES`; the heading in `help` follows
   from it, so there is nothing to keep in step. Do **not** give it a
   plain-word alias: two groups could each want `read`, and a test enforces
   that namespaced commands have none.

   Note the word *namespace* is internal. To the reader there are only
   commands, some of which take a subcommand — a test sweeps every help page,
   topic and error to keep the word out of what they see.

   A name with no colon is a **top-level** command, reserved for the shell's
   own vocabulary (`help`, `set`, `exit`). Anything that touches the target
   belongs in a namespace, and a test enforces that too.

   ```python
   def _mycommand_parser() -> CommandParser:
       parser = CommandParser("memory:mycommand")
       parser.add_argument("address", help="what to act on")
       return parser


   @command(
       "memory:mycommand",
       parser=_mycommand_parser,
       summary="One line, sentence case, ending in a period.",
       details="The long help, printed by 'help memory:mycommand'.",
       examples=("memory:mycommand 0x1000",),
   )
   def cmd_mycommand(session: Session, args: List[str]) -> None:
       options = _mycommand_parser().parse_args(args)

       process = session.require_process("memory:mycommand")
       address = parse_address(options.address, session)
       ...
   ```

   There is no `usage=`: the usage line is generated from the parser, so it
   always names every flag the command accepts. Give each argument a `help=`
   and a readable `metavar` — those two are what the help is built from.

   If the command prints a table that can be longer than a screen, page it
   with the shared helpers rather than a `--limit` of your own:

   ```python
   def _mycommand_parser() -> CommandParser:
       return add_paging_arguments(CommandParser("memory:mycommand"))


   page = paginate(
       session, rows, command="memory:mycommand",
       limit=options.limit, page=options.page, show_all=options.all,
   )
   session.printer.table(headers, page.rows, total=page.total,
                         page=page.number, pages=page.count,
                         next_page=page.next_page)
   ```

   That gives the same three flags, the same wording, the same
   `page N of M` footer and the same `Next page: ...` line as every other
   listing — and a test enforces that the wording does not drift.

   Names go **two levels at most** — `scan:keep`, never `scan:results:keep`.
   The registry rejects a third level, and a test pins that down: a deeper name
   buys tidiness at the cost of a listing that has to be walked twice to be
   read once.

   `<command>:help` is a dispatcher convention rather than a registered
   command, so it answers for every command at every depth — `memory:help`,
   `memory:read:help`, `clear:help` — without one `help` command per group
   cluttering the listings it exists to print. It keeps working, but the
   spelling the help *advertises* is `help <command>`: one form for everything,
   and it reads as a sentence.

3. Use `CommandParser`, not a bare `ArgumentParser`: it raises instead of
   calling `sys.exit`, which would kill the shell on a typo.
4. Take addresses through `parse_address` so your command speaks the same
   `[game.exe+0x10]+0x8` and `#3` language as every other one.

Pass every argument a `help=` string. `help <command>` (and `<command> --help`)
builds its **Arguments** and **Options** sections from the parser itself, so
the documentation cannot drift from what the command accepts — there is only
one definition of either.

`help` and `picklock --help` are likewise generated from the registry, so a
command cannot be added without also being documented. `tests/test_commands.py`
enforces all of it: every command must declare a parser, every argument must
carry help text, every flag must appear in the command's help, and a usage line
may not advertise a flag the parser does not accept. A new command is covered
the moment it is registered.

## Submitting changes

1. Open an issue first for bug reports or substantial features.
2. Branch from `main`. Keep commits focused.
3. Run `make pre-commit` locally before pushing.
4. PR titles follow [Conventional Commits][cc] (`feat:`, `fix:`, `docs:`, …) —
   CI lints the title.
5. Describe the change and how it was tested. For a command body, paste the
   session.

## Reporting bugs

Please include:

- The output of `picklock -e "version"` — it names Picklock, PyMemoryEditor,
  Python and the platform.
- The exact command you typed and the exact output you got.
- Whether you were running elevated (`sudo` / Administrator).
- For Linux: whether `/proc/sys/kernel/yama/ptrace_scope` is `0` or `1`.

## Security

If you find a security issue, please see [`SECURITY.md`](SECURITY.md).
**Do not** report it via GitHub issues.

[pyme]: https://github.com/JeanExtreme002/PyMemoryEditor
[cc]: https://www.conventionalcommits.org/
