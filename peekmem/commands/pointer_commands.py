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


@command(
    "deref",
    summary="Walk a pointer chain and print the address it lands on.",
    usage="deref <base> [offset ...]",
    group="Pointers",
    aliases=("resolve",),
    details=(
        "Reads the pointer at BASE, adds the first offset, reads the pointer "
        "there, and so on; the last offset is added without a final read — the "
        "Cheat Engine convention, so a chain copied from a cheat table works "
        "unchanged.\n\n"
        "BASE is a full address expression, so 'deref game.exe+0x1a2b3c 0x10 "
        "0x8' is the usual spelling."
    ),
    examples=("deref game.exe+0x1a2b3c 0x10 0x8", "deref 0x7ffee3a01000 0x18"),
)
def cmd_deref(session: Session, args: List[str]) -> None:
    parser = CommandParser("deref")
    parser.add_argument("base")
    parser.add_argument("offsets", nargs="*")
    options = parser.parse_args(args)

    process = session.require_process("deref")
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


@command(
    "pointer",
    summary="Read or write the value at the end of a pointer chain.",
    usage="pointer <base> [offset ...] [--type T] [--length N] [--write VALUE]",
    group="Pointers",
    aliases=("ptr",),
    details=(
        "Resolves the chain and then reads (or, with --write, writes) the "
        "value there — the one-line form of 'deref' followed by 'read'.\n\n"
        "The chain is re-walked on every call, which is the point: it keeps "
        "working after the target reallocates whatever the last link pointed "
        "at."
    ),
    examples=(
        "pointer game.exe+0x1a2b3c 0x10 0x8 --type int32",
        "pointer game.exe+0x1a2b3c 0x10 --write 999",
    ),
)
def cmd_pointer(session: Session, args: List[str]) -> None:
    parser = CommandParser("pointer")
    parser.add_argument("base")
    parser.add_argument("offsets", nargs="*")
    parser.add_argument("--type", dest="value_type", default=None)
    parser.add_argument("--length", type=int, default=None)
    parser.add_argument("--write", default=None)
    options = parser.parse_args(args)

    process = session.require_process("pointer")
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


@command(
    "ptrscan",
    summary="Find static pointer paths that reach an address.",
    usage="ptrscan <address> [--depth N] [--max-offset N] [--max N] [--unaligned] [--all-regions]",
    group="Pointers",
    aliases=("pointerscan",),
    details=(
        "Builds a map of every pointer in the target and walks it backwards "
        "from ADDRESS until it reaches a static base inside a module. The "
        "paths found replace whatever 'paths' was showing.\n\n"
        "  --depth N        maximum number of links (default 3). Each extra\n"
        "                   level costs a lot of time and memory.\n"
        "  --max-offset N   largest offset to consider (default 1024)\n"
        "  --max N          stop after N paths\n"
        "  --unaligned      also consider pointers not on a pointer-size\n"
        "                   boundary (slower, rarely needed)\n"
        "  --all-regions    include non-writable regions in the pointer map\n\n"
        "This is the expensive command in Peekmem: minutes and hundreds of "
        "megabytes on a large target. Ctrl+C stops it and keeps the paths "
        "found so far.\n\n"
        "A path is only worth trusting once it has survived a restart: save "
        "the paths, restart the target, find the address again, and run "
        "'ptrrescan' — see 'help ptrrescan'."
    ),
    examples=("ptrscan #1", "ptrscan 0x7ffee3a01000 --depth 4 --max 200"),
)
def cmd_ptrscan(session: Session, args: List[str]) -> None:
    parser = CommandParser("ptrscan")
    parser.add_argument("address")
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--max-offset", type=int, default=1024)
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--unaligned", action="store_true")
    parser.add_argument("--all-regions", action="store_true")
    options = parser.parse_args(args)

    process = session.require_process("ptrscan")
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


@command(
    "paths",
    summary="Show the pointer paths currently held.",
    usage="paths [--limit N] [--all]",
    group="Pointers",
    details=(
        "Lists the paths from the last 'ptrscan', 'ptrload', 'ptrrescan' or "
        "'ptrdiff'. TARGET is where each one resolves right now, so a path "
        "that has gone stale shows as '(unresolved)'."
    ),
)
def cmd_paths(session: Session, args: List[str]) -> None:
    parser = CommandParser("paths")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--all", action="store_true")
    options = parser.parse_args(args)

    session.require_process("paths")
    if not session.pointer_paths:
        raise CommandError('No pointer paths. Run "ptrscan <address>" first.')

    limit = None if options.all else session.display_limit(options.limit)
    _print_paths(session, session.pointer_paths, limit=limit)


@command(
    "ptrsave",
    summary="Save the current pointer paths to a file.",
    usage="ptrsave <file>",
    group="Pointers",
    details=(
        "Writes the paths as JSON, keeping the module name and module-relative "
        "offset of each base so the file survives ASLR and can be re-used "
        "after the target restarts."
    ),
    examples=("ptrsave health.json",),
)
def cmd_ptrsave(session: Session, args: List[str]) -> None:
    parser = CommandParser("ptrsave")
    parser.add_argument("file")
    options = parser.parse_args(args)

    process = session.require_process("ptrsave")
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


@command(
    "ptrload",
    summary="Load pointer paths from a file.",
    usage="ptrload <file>",
    group="Pointers",
    details=(
        "Replaces the paths currently held. Each base is rebased onto the "
        "module addresses of the *running* target, so a file saved before a "
        "restart resolves correctly after it."
    ),
    examples=("ptrload health.json",),
)
def cmd_ptrload(session: Session, args: List[str]) -> None:
    parser = CommandParser("ptrload")
    parser.add_argument("file")
    options = parser.parse_args(args)

    process = session.require_process("ptrload")
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


@command(
    "ptrrescan",
    summary="Keep only the paths that still reach an address.",
    usage="ptrrescan <address> [file]",
    group="Pointers",
    details=(
        "The step that separates a real pointer path from a coincidence. "
        "Restart the target, find the value's new address, then rescan the "
        "saved paths against it: the ones that still land on the address are "
        "the ones that describe the structure rather than that one run.\n\n"
        "Without FILE, the paths currently held are rescanned."
    ),
    examples=("ptrrescan #1", "ptrrescan 0x7ffee3a01000 health.json"),
)
def cmd_ptrrescan(session: Session, args: List[str]) -> None:
    parser = CommandParser("ptrrescan")
    parser.add_argument("address")
    parser.add_argument("file", nargs="?", default=None)
    options = parser.parse_args(args)

    process = session.require_process("ptrrescan")
    target = parse_address(options.address, session)

    source: Any = options.file
    if source is None:
        if not session.pointer_paths:
            raise CommandError("No pointer paths to rescan. Give a file, or run 'ptrscan'.")
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


@command(
    "ptrdiff",
    summary="Intersect pointer-path files from several runs.",
    usage="ptrdiff <file> <file> [file ...]",
    group="Pointers",
    details=(
        "Keeps only the paths present in *every* file, compared by their "
        "portable recipe (module, module offset, offsets) rather than by "
        "absolute address. Two or three runs of the same target usually leave "
        "a handful of paths standing, and those are the reliable ones.\n\n"
        "The result replaces the paths currently held, so 'ptrsave' can write "
        "it straight back out."
    ),
    examples=("ptrdiff run1.json run2.json", "ptrdiff run1.json run2.json run3.json"),
)
def cmd_ptrdiff(session: Session, args: List[str]) -> None:
    parser = CommandParser("ptrdiff")
    parser.add_argument("files", nargs="*")
    options = parser.parse_args(args)

    process = session.require_process("ptrdiff")
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
