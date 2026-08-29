# -*- coding: utf-8 -*-

"""
Pointer chains: following them, and finding them.

An address found by a scan is only good until the target restarts — the
allocation that held it moves. What survives is the *path* to it: a static
base inside a module plus a list of offsets to dereference. ``deref`` and
``pointer`` walk a path you already know; ``ptrscan`` searches for the paths
that reach an address, and ``ptrsave`` / ``ptrload`` / ``ptrrescan`` /
``ptrdiff`` are the workflow that turns a pile of candidates into the one path
that holds across runs.
"""

import os
from typing import Any, List, Optional, Sequence

from PyMemoryEditor import PointerPath

from .. import valuetypes
from ..addressing import parse_address, parse_int
from ..errors import CommandError
from ..output import LEFT, RIGHT, Timer, format_address
from ..session import Session
from . import CommandParser, command

_BASE_HELP = (
    "the static base of the chain, as an address expression — usually "
    "module+offset (see 'help address')"
)
_OFFSETS_HELP = (
    "offsets to walk, in order; hex accepted. The last one is added without a "
    "final read, matching the Cheat Engine convention"
)


def _parse_offsets(tokens: Sequence[str]) -> List[int]:
    return [parse_int(token, "offset") for token in tokens]


def _describe_base(path: PointerPath, pointer_size: int) -> str:
    """Render a path's base the portable way when we can, absolutely otherwise."""
    if path.module and path.module_offset is not None:
        return f"{path.module}+0x{path.module_offset:X}"
    return format_address(path.base_address, pointer_size)


def _describe_offsets(path: PointerPath) -> str:
    return " ".join(f"0x{offset:X}" for offset in path.offsets) or "(none)"


def _print_paths(
    session: Session,
    paths: Sequence[PointerPath],
    *,
    limit: Optional[int],
    elapsed: Optional[float] = None,
) -> None:
    process = session.require_process()
    pointer_size = process.pointer_size
    shown = paths[:limit] if limit else paths

    rows = []
    for index, path in enumerate(shown):
        try:
            target = format_address(path.resolve(process), pointer_size)
        except (OSError, ValueError):
            # A path that no longer resolves is exactly what a rescan is for,
            # so report it as a row rather than failing the whole listing.
            target = "(unresolved)"
        rows.append(
            (f"#{index + 1}", _describe_base(path, pointer_size), _describe_offsets(path), target)
        )

    session.printer.table(
        ("ROW", "BASE", "OFFSETS", "TARGET"),
        rows,
        (RIGHT, LEFT, LEFT, LEFT),
        elapsed=elapsed,
        total=len(paths),
    )


def _deref_parser() -> CommandParser:
    parser = CommandParser("pointer:deref")
    parser.add_argument("base", help=_BASE_HELP)
    parser.add_argument("offsets", nargs="*", help=_OFFSETS_HELP)
    return parser


@command(
    "pointer:deref",
    parser=_deref_parser,
    summary="Walk a pointer chain and print the address it lands on.",
    usage="pointer:deref <base> [offset ...]",
    details=(
        "Reads the pointer at BASE, adds the first offset, reads the pointer "
        "there, and so on; the last offset is added without a final read — the "
        "Cheat Engine convention, so a chain copied from a cheat table works "
        "unchanged."
    ),
    examples=("pointer:deref game.exe+0x1a2b3c 0x10 0x8", "pointer:deref 0x7ffee3a01000 0x18"),
)
def cmd_deref(session: Session, args: List[str]) -> None:
    options = _deref_parser().parse_args(args)

    process = session.require_process("pointer:deref")
    base = parse_address(options.base, session)
    offsets = _parse_offsets(options.offsets)

    with Timer() as timer:
        try:
            address = process.resolve_pointer_chain(base, offsets)
        except OSError as error:
            raise CommandError(f"The chain does not resolve: {error}")

    session.printer.table(
        ("BASE", "OFFSETS", "TARGET"),
        [
            (
                format_address(base, process.pointer_size),
                " ".join(f"0x{offset:X}" for offset in offsets) or "(none)",
                format_address(address, process.pointer_size),
            )
        ],
        (LEFT, LEFT, LEFT),
        elapsed=timer.elapsed,
    )


def _pointer_parser() -> CommandParser:
    parser = CommandParser("pointer:read")
    parser.add_argument("base", help=_BASE_HELP)
    parser.add_argument("offsets", nargs="*", help=_OFFSETS_HELP)
    parser.add_argument(
        "--type",
        dest="value_type",
        default=None,
        metavar="TYPE",
        help="value type at the end of the chain; defaults to int32",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=None,
        metavar="N",
        help="byte width, required for the 'string' and 'bytes' types",
    )
    parser.add_argument(
        "--write",
        default=None,
        metavar="VALUE",
        help="write this value at the end of the chain instead of reading it",
    )
    return parser


@command(
    "pointer:read",
    parser=_pointer_parser,
    summary="Read or write the value at the end of a pointer chain.",
    usage="pointer:read <base> [offset ...] [--type T] [--length N] [--write VALUE]",
    details=(
        "The one-line form of 'pointer:deref' followed by 'memory:read'.\n\n"
        "The chain is re-walked on every call, which is the point: it keeps "
        "working after the target reallocates whatever the last link pointed "
        "at."
    ),
    examples=(
        "pointer:read game.exe+0x1a2b3c 0x10 0x8 --type int32",
        "pointer:read game.exe+0x1a2b3c 0x10 --write 999",
    ),
)
def cmd_pointer(session: Session, args: List[str]) -> None:
    options = _pointer_parser().parse_args(args)

    process = session.require_process("pointer:read")
    value_type = (
        valuetypes.DEFAULT_TYPE
        if options.value_type is None
        else valuetypes.resolve(options.value_type)
    )
    base = parse_address(options.base, session)
    offsets = _parse_offsets(options.offsets)

    with Timer() as timer:
        try:
            if options.write is not None:
                value = value_type.parse(options.write)
                width = value_type.width_for(value, options.length)
                remote = process.get_pointer(
                    base, offsets, pytype=value_type.pytype, bufflength=width
                )
                address = remote.address
                remote.write(value_type.encode(value))
                action = f"Wrote {width} byte(s) to"
            else:
                width = value_type.read_width(options.length)
                remote = process.get_pointer(
                    base, offsets, pytype=value_type.pytype, bufflength=width
                )
                address = remote.address
                value = value_type.decode(remote.read())
                action = None
        except OSError as error:
            raise CommandError(f"The chain does not resolve: {error}")

    if action is not None:
        session.printer.ok(
            f"{action} {format_address(address, process.pointer_size)}.",
            elapsed=timer.elapsed,
        )
        session.printer.write()
        return

    session.printer.table(
        ("ADDRESS", "TYPE", "VALUE"),
        [
            (
                format_address(address, process.pointer_size),
                value_type.name,
                value_type.format(value, hex_output=bool(session.option("hex"))),
            )
        ],
        (LEFT, LEFT, LEFT),
        elapsed=timer.elapsed,
    )


def _ptrscan_parser() -> CommandParser:
    parser = CommandParser("pointer:scan")
    parser.add_argument(
        "address",
        help="the address to find paths to, as an address expression — "
        "usually '#1' straight from a scan",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=3,
        metavar="N",
        help="maximum number of links in a chain (default 3). Each extra "
        "level costs a lot of time and memory",
    )
    parser.add_argument(
        "--max-offset",
        type=int,
        default=1024,
        metavar="N",
        help="largest offset to consider (default 1024)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        metavar="N",
        help="stop after N paths",
    )
    parser.add_argument(
        "--unaligned",
        action="store_true",
        help="also consider pointers not on a pointer-size boundary — slower, "
        "and rarely needed",
    )
    parser.add_argument(
        "--all-regions",
        action="store_true",
        help="include non-writable regions in the pointer map",
    )
    return parser


@command(
    "pointer:scan",
    parser=_ptrscan_parser,
    summary="Find static pointer paths that reach an address.",
    usage="pointer:scan <address> [--depth N] [--max-offset N] [--max N] [--unaligned] [--all-regions]",
    details=(
        "Builds a map of every pointer in the target and walks it backwards "
        "from ADDRESS until it reaches a static base inside a module. The "
        "paths found replace whatever 'pointer:paths' was showing.\n\n"
        "This is the expensive command in Peekmem: minutes and hundreds of "
        "megabytes on a large target. Ctrl+C stops it and keeps the paths "
        "found so far.\n\n"
        "A path is only worth trusting once it has survived a restart: save "
        "the paths, restart the target, find the address again, and run "
        "'pointer:rescan' — see 'help pointer:rescan'."
    ),
    examples=("pointer:scan #1", "pointer:scan 0x7ffee3a01000 --depth 4 --max 200"),
)
def cmd_ptrscan(session: Session, args: List[str]) -> None:
    options = _ptrscan_parser().parse_args(args)

    process = session.require_process("pointer:scan")
    target = parse_address(options.address, session)

    if options.depth < 1:
        raise CommandError("--depth must be at least 1.")
    if options.max_offset < 0:
        raise CommandError("--max-offset cannot be negative.")

    printer = session.printer
    show_progress = bool(session.option("progress"))

    def on_progress(fraction: float) -> None:
        if show_progress:
            printer.progress("Mapping pointers", fraction)

    paths: List[PointerPath] = []
    interrupted = False

    with Timer() as timer:
        try:
            for path in process.scan_pointer_paths(
                target,
                max_depth=options.depth,
                max_offset=options.max_offset,
                aligned=not options.unaligned,
                writable_only=not options.all_regions,
                max_results=options.max,
                progress_callback=on_progress,
            ):
                paths.append(path)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            printer.clear_progress()

    session.pointer_paths = paths

    if interrupted:
        printer.note("Interrupted — showing the paths found so far.")
    if not paths:
        printer.note(
            "No static path reaches that address. Try a greater --depth or a "
            "larger --max-offset, or check that the address is still valid."
        )

    _print_paths(session, paths, limit=session.display_limit(), elapsed=timer.elapsed)


def _paths_parser() -> CommandParser:
    parser = CommandParser("pointer:paths")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="print at most N rows, overriding the 'limit' setting",
    )
    parser.add_argument(
        "--all", action="store_true", help="print every path, ignoring the limit"
    )
    return parser


@command(
    "pointer:paths",
    parser=_paths_parser,
    summary="Show the pointer paths currently held.",
    usage="pointer:paths [--limit N] [--all]",
    details=(
        "Lists the paths from the last 'pointer:scan', 'pointer:load', "
        "'pointer:rescan' or 'pointer:diff'. TARGET is where each one resolves "
        "right now, so a path "
        "that has gone stale shows as '(unresolved)'."
    ),
)
def cmd_paths(session: Session, args: List[str]) -> None:
    options = _paths_parser().parse_args(args)

    session.require_process("pointer:paths")
    if not session.pointer_paths:
        raise CommandError('No pointer paths. Run "pointer:scan <address>" first.')

    limit = None if options.all else session.display_limit(options.limit)
    _print_paths(session, session.pointer_paths, limit=limit)


def _ptrsave_parser() -> CommandParser:
    parser = CommandParser("pointer:save")
    parser.add_argument("file", help="path of the JSON file to write")
    return parser


@command(
    "pointer:save",
    parser=_ptrsave_parser,
    summary="Save the current pointer paths to a file.",
    usage="pointer:save <file>",
    details=(
        "Writes the paths as JSON, keeping the module name and module-relative "
        "offset of each base so the file survives ASLR and can be re-used "
        "after the target restarts."
    ),
    examples=("pointer:save health.json",),
)
def cmd_ptrsave(session: Session, args: List[str]) -> None:
    options = _ptrsave_parser().parse_args(args)

    process = session.require_process("pointer:save")
    if not session.pointer_paths:
        raise CommandError("No pointer paths to save.")

    with Timer() as timer:
        try:
            process.save_pointer_paths(session.pointer_paths, options.file)
        except OSError as error:
            raise CommandError(f"Cannot write {options.file!r}: {error}")

    session.printer.ok(
        f"Saved {len(session.pointer_paths)} path(s) to {options.file}.",
        elapsed=timer.elapsed,
    )
    session.printer.write()


def _ptrload_parser() -> CommandParser:
    parser = CommandParser("pointer:load")
    parser.add_argument("file", help="path of a JSON file written by 'pointer:save'")
    return parser


@command(
    "pointer:load",
    parser=_ptrload_parser,
    summary="Load pointer paths from a file.",
    usage="pointer:load <file>",
    details=(
        "Replaces the paths currently held. Each base is rebased onto the "
        "module addresses of the *running* target, so a file saved before a "
        "restart resolves correctly after it."
    ),
    examples=("pointer:load health.json",),
)
def cmd_ptrload(session: Session, args: List[str]) -> None:
    options = _ptrload_parser().parse_args(args)

    process = session.require_process("pointer:load")
    if not os.path.exists(options.file):
        raise CommandError(f"No such file: {options.file}")

    with Timer() as timer:
        try:
            loaded = process.load_pointer_paths(options.file)
        except (OSError, ValueError) as error:
            raise CommandError(f"Cannot read {options.file!r}: {error}")

        rebased: List[PointerPath] = []
        for path in loaded:
            try:
                rebased.append(path.rebase(process))
            except (ValueError, KeyError):
                # The module is not loaded in this run; keep the absolute base
                # rather than dropping a path the user may still want to see.
                rebased.append(path)

    session.pointer_paths = rebased
    session.printer.ok(
        f"Loaded {len(rebased)} path(s) from {options.file}.", elapsed=timer.elapsed
    )
    session.printer.write()
    _print_paths(session, rebased, limit=session.display_limit())


def _ptrrescan_parser() -> CommandParser:
    parser = CommandParser("pointer:rescan")
    parser.add_argument(
        "address",
        help="the address the surviving paths must reach, as an address "
        "expression — usually '#1' from the scan that found it again",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="rescan the paths in this file; without it, the paths currently "
        "held are rescanned",
    )
    return parser


@command(
    "pointer:rescan",
    parser=_ptrrescan_parser,
    summary="Keep only the paths that still reach an address.",
    usage="pointer:rescan <address> [file]",
    details=(
        "The step that separates a real pointer path from a coincidence. "
        "Restart the target, find the value's new address, then rescan the "
        "saved paths against it: the ones that still land on the address are "
        "the ones that describe the structure rather than that one run."
    ),
    examples=("pointer:rescan #1", "pointer:rescan 0x7ffee3a01000 health.json"),
)
def cmd_ptrrescan(session: Session, args: List[str]) -> None:
    options = _ptrrescan_parser().parse_args(args)

    process = session.require_process("pointer:rescan")
    target = parse_address(options.address, session)

    source: Any = options.file
    if source is None:
        if not session.pointer_paths:
            raise CommandError(
                "No pointer paths to rescan. Give a file, or run 'pointer:scan'."
            )
        source = session.pointer_paths
    elif not os.path.exists(source):
        raise CommandError(f"No such file: {source}")

    before = len(session.pointer_paths) if options.file is None else None

    with Timer() as timer:
        try:
            surviving = process.rescan_pointer_paths(source, target)
        except (OSError, ValueError) as error:
            raise CommandError(f"Rescan failed: {error}")

    session.pointer_paths = surviving

    detail = f" (of {before})" if before is not None else ""
    session.printer.ok(
        f"{len(surviving)} path(s){detail} still reach "
        f"{format_address(target, process.pointer_size)}.",
        elapsed=timer.elapsed,
    )
    session.printer.write()
    _print_paths(session, surviving, limit=session.display_limit())


def _ptrdiff_parser() -> CommandParser:
    parser = CommandParser("pointer:diff")
    parser.add_argument(
        "files",
        nargs="*",
        help="two or more JSON files written by 'pointer:save', one per run of the "
        "target",
    )
    return parser


@command(
    "pointer:diff",
    parser=_ptrdiff_parser,
    summary="Intersect pointer-path files from several runs.",
    usage="pointer:diff <file> <file> [file ...]",
    details=(
        "Keeps only the paths present in *every* file, compared by their "
        "portable recipe (module, module offset, offsets) rather than by "
        "absolute address. Two or three runs of the same target usually leave "
        "a handful of paths standing, and those are the reliable ones.\n\n"
        "The result replaces the paths currently held, so 'pointer:save' can write "
        "it straight back out."
    ),
    examples=("pointer:diff run1.json run2.json", "pointer:diff run1.json run2.json run3.json"),
)
def cmd_ptrdiff(session: Session, args: List[str]) -> None:
    options = _ptrdiff_parser().parse_args(args)

    process = session.require_process("pointer:diff")
    if len(options.files) < 2:
        raise CommandError("ptrdiff needs at least two files.")
    for name in options.files:
        if not os.path.exists(name):
            raise CommandError(f"No such file: {name}")

    with Timer() as timer:
        try:
            common = process.compare_pointer_scans(*options.files)
        except (OSError, ValueError) as error:
            raise CommandError(f"Comparison failed: {error}")

    session.pointer_paths = common
    session.printer.ok(
        f"{len(common)} path(s) present in all {len(options.files)} file(s).",
        elapsed=timer.elapsed,
    )
    session.printer.write()
    _print_paths(session, common, limit=session.display_limit())


__all__ = ()
