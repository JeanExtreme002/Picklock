# -*- coding: utf-8 -*-

"""
Looking at, and changing, the target's memory.

``regions`` / ``modules`` / ``threads`` describe the address space; ``read`` /
``write`` / ``dump`` / ``watch`` work on a single address; ``alloc`` / ``free``
hand the target new pages.
"""

import time
from typing import Any, List, Optional

from .. import valuetypes
from ..addressing import parse_address, parse_int
from ..errors import CommandError
from ..output import LEFT, RIGHT, Timer, format_address, format_size, render_hexdump
from ..session import Session
from ..valuetypes import ValueType
from . import CommandParser, command


def _resolve_type(name: Optional[str]) -> ValueType:
    return valuetypes.DEFAULT_TYPE if name is None else valuetypes.resolve(name)


def _permissions(region) -> str:
    """Render a region's access bits the way ``/proc/*/maps`` does."""
    return "".join(
        (
            "r" if region.is_readable else "-",
            "w" if region.is_writable else "-",
            "x" if region.is_executable else "-",
            "s" if region.is_shared else "p",
        )
    )


@command(
    "regions",
    summary="List the target's mapped memory regions.",
    usage="regions [--writable] [--executable] [--path TEXT] [--at ADDRESS] [--limit N]",
    group="Memory",
    aliases=("maps",),
    details=(
        "The memory map is re-read on every call, so it reflects allocations "
        "the target made since the last look.\n\n"
        "  --writable / --executable / --shared   keep only regions with that bit\n"
        "  --path TEXT   keep regions backed by a file whose path contains TEXT\n"
        "  --at ADDRESS  show only the region containing ADDRESS\n\n"
        "The PERMS column reads like /proc/<pid>/maps: rwx plus 's' for a "
        "shared/file-backed mapping or 'p' for a private one."
    ),
    examples=("regions --writable", "regions --at 0x7ffee3a01000", "regions --path libc"),
)
def cmd_regions(session: Session, args: List[str]) -> None:
    parser = CommandParser("regions")
    parser.add_argument("--writable", action="store_true")
    parser.add_argument("--executable", action="store_true")
    parser.add_argument("--shared", action="store_true")
    parser.add_argument("--path", default=None)
    parser.add_argument("--at", default=None)
    parser.add_argument("--limit", type=int, default=None)
    options = parser.parse_args(args)

    process = session.require_process("regions")

    with Timer() as timer:
        regions = session.regions(refresh=True)

        if options.writable:
            regions = [region for region in regions if region.is_writable]
        if options.executable:
            regions = [region for region in regions if region.is_executable]
        if options.shared:
            regions = [region for region in regions if region.is_shared]
        if options.path:
            needle = options.path.lower()
            regions = [region for region in regions if needle in region.path.lower()]
        if options.at is not None:
            address = parse_address(options.at, session)
            regions = [
                region
                for region in regions
                if region.address <= address < region.address + region.size
            ]

    limit = session.display_limit(options.limit)
    shown = regions[:limit] if limit else regions
    pointer_size = process.pointer_size

    session.printer.table(
        ("ADDRESS", "SIZE", "PERMS", "PATH"),
        [
            (
                format_address(region.address, pointer_size),
                format_size(region.size),
                _permissions(region),
                region.path,
            )
            for region in shown
        ],
        (LEFT, RIGHT, LEFT, LEFT),
        elapsed=timer.elapsed,
        total=len(regions),
    )


@command(
    "modules",
    summary="List the modules loaded in the target.",
    usage="modules [pattern] [--limit N]",
    group="Memory",
    details=(
        "A module is the main executable or a shared library (.dll / .so / "
        ".dylib). Its BASE moves on every launch under ASLR, which is why an "
        "address is best written as 'module+offset' — see 'help address'.\n\n"
        "Running this command refreshes the module table the address parser "
        "uses, so run it after the target loads a library."
    ),
    examples=("modules", "modules libc"),
)
def cmd_modules(session: Session, args: List[str]) -> None:
    parser = CommandParser("modules")
    parser.add_argument("pattern", nargs="?", default=None)
    parser.add_argument("--limit", type=int, default=None)
    options = parser.parse_args(args)

    process = session.require_process("modules")

    with Timer() as timer:
        modules = list(process.get_modules())
        session.invalidate()
        session.modules(refresh=True)

    if options.pattern:
        needle = options.pattern.lower()
        modules = [
            module
            for module in modules
            if needle in module.name.lower() or needle in module.path.lower()
        ]

    limit = session.display_limit(options.limit)
    shown = modules[:limit] if limit else modules
    pointer_size = process.pointer_size

    session.printer.table(
        ("NAME", "BASE", "SIZE", "PATH"),
        [
            (
                module.name,
                format_address(module.base_address, pointer_size),
                format_size(module.size) if module.size else "?",
                module.path,
            )
            for module in shown
        ],
        (LEFT, LEFT, RIGHT, LEFT),
        elapsed=timer.elapsed,
        total=len(modules),
    )


@command(
    "threads",
    summary="List the target's threads.",
    usage="threads [--limit N]",
    group="Memory",
    details=(
        "STATE and PRIORITY are filled in only where the platform exposes them "
        "cheaply (Linux does; Windows and macOS leave them empty). The meaning "
        "of TID is platform-specific: a POSIX task id on Linux, a kernel "
        "thread id on Windows, a Mach port name on macOS."
    ),
)
def cmd_threads(session: Session, args: List[str]) -> None:
    parser = CommandParser("threads")
    parser.add_argument("--limit", type=int, default=None)
    options = parser.parse_args(args)

    process = session.require_process("threads")

    with Timer() as timer:
        threads = list(process.get_threads())

    limit = session.display_limit(options.limit)
    shown = threads[:limit] if limit else threads

    session.printer.table(
        ("TID", "STATE", "PRIORITY"),
        [
            (
                thread.tid,
                thread.state if thread.state is not None else "",
                thread.priority if thread.priority is not None else "",
            )
            for thread in shown
        ],
        (RIGHT, LEFT, RIGHT),
        elapsed=timer.elapsed,
        total=len(threads),
    )


@command(
    "read",
    summary="Read a typed value from an address.",
    usage="read <address> [type] [length] [--count N] [--hex]",
    group="Memory",
    aliases=("peek",),
    details=(
        "The type defaults to int32. 'string' and 'bytes' need a length in "
        "bytes; the fixed-width types ignore one.\n\n"
        "  --count N   read N consecutive values, stepping by the type's width\n"
        "  --hex       print integers in hexadecimal\n\n"
        "The address is an expression — see 'help address' — so a pointer "
        "chain can be read in one go."
    ),
    examples=(
        "read 0x7ffee3a01000",
        "read game.exe+0x1234 int32",
        "read [game.exe+0x1a2b3c]+0x18 float",
        "read 0x7ffee3a01000 string 32",
        "read #1 int32 --count 8",
    ),
)
def cmd_read(session: Session, args: List[str]) -> None:
    parser = CommandParser("read")
    parser.add_argument("address")
    parser.add_argument("type", nargs="?", default=None)
    parser.add_argument("length", nargs="?", type=int, default=None)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--hex", action="store_true")
    options = parser.parse_args(args)

    process = session.require_process("read")
    value_type = _resolve_type(options.type)
    width = value_type.read_width(options.length)

    if options.count < 1:
        raise CommandError("--count must be at least 1.")

    base = parse_address(options.address, session)
    hex_output = options.hex or bool(session.option("hex"))
    rows = []

    with Timer() as timer:
        for index in range(options.count):
            address = base + index * width
            try:
                raw: Any = process.read_process_memory(
                    address, value_type.pytype, width
                )
            except OSError as error:
                raise CommandError(f"Cannot read 0x{address:X}: {error}")
            rows.append(
                (
                    format_address(address, process.pointer_size),
                    value_type.name,
                    value_type.format(value_type.decode(raw), hex_output=hex_output),
                )
            )

    session.printer.table(
        ("ADDRESS", "TYPE", "VALUE"),
        rows,
        (LEFT, LEFT, LEFT),
        elapsed=timer.elapsed,
    )


@command(
    "write",
    summary="Write a typed value to an address.",
    usage="write <address> <type> <value> [--length N] [--null-terminated]",
    group="Memory",
    aliases=("poke",),
    details=(
        "The value is parsed according to the type: integers accept 0x/0o/0b "
        "prefixes, booleans accept true/false/on/off, 'bytes' takes hex "
        "('DE AD BE EF') and 'string' takes the text verbatim.\n\n"
        "  --length N          buffer width for string/bytes; defaults to the\n"
        "                      natural width of the value given\n"
        "  --null-terminated   append a NUL after a string (C-string writes)\n\n"
        "There is no confirmation and no undo. Writing into a live process can "
        "crash it — read the address first if you are not sure of it."
    ),
    examples=(
        "write 0x7ffee3a01000 int32 100",
        "write game.exe+0x1234 float 99.5",
        "write #2 bytes 'DE AD BE EF'",
        "write 0x7ffee3a01000 string Peekmem --null-terminated",
    ),
)
def cmd_write(session: Session, args: List[str]) -> None:
    parser = CommandParser("write")
    parser.add_argument("address")
    parser.add_argument("type")
    parser.add_argument("value")
    parser.add_argument("--length", type=int, default=None)
    parser.add_argument("--null-terminated", action="store_true")
    options = parser.parse_args(args)

    process = session.require_process("write")
    value_type = valuetypes.resolve(options.type)
    value = value_type.parse(options.value)
    width = value_type.width_for(value, options.length)
    address = parse_address(options.address, session)

    if options.null_terminated and value_type.pytype is not str:
        raise CommandError("--null-terminated only applies to the 'string' type.")

    with Timer() as timer:
        try:
            if options.null_terminated:
                process.write_string(address, value, null_terminator=True)
            else:
                process.write_process_memory(
                    address, value_type.pytype, width, value_type.encode(value)
                )
        except OSError as error:
            raise CommandError(f"Cannot write to 0x{address:X}: {error}")

    session.printer.ok(
        f"Wrote {width} byte(s) to {format_address(address, process.pointer_size)}.",
        elapsed=timer.elapsed,
    )
    session.printer.write()


@command(
    "dump",
    summary="Hex-dump a range of memory.",
    usage="dump <address> [length] [--width N]",
    group="Memory",
    aliases=("hexdump", "x"),
    details=(
        "Prints the classic three-column layout: absolute address, hex bytes, "
        "printable ASCII. Length defaults to 256 bytes and the line width to "
        "the 'dump_width' setting.\n\n"
        "The read is a single call, so a range that crosses into an unmapped "
        "page fails as a whole rather than returning half the bytes."
    ),
    examples=("dump 0x7ffee3a01000", "dump game.exe+0x1000 512", "dump #1 64 --width 8"),
)
def cmd_dump(session: Session, args: List[str]) -> None:
    parser = CommandParser("dump")
    parser.add_argument("address")
    parser.add_argument("length", nargs="?", default="256")
    parser.add_argument("--width", type=int, default=None)
    options = parser.parse_args(args)

    process = session.require_process("dump")
    address = parse_address(options.address, session)
    length = parse_int(str(options.length), "length")
    width = options.width if options.width else int(session.option("dump_width"))

    if length < 1:
        raise CommandError("Length must be at least 1 byte.")
    if width < 1:
        raise CommandError("Line width must be at least 1 byte.")

    with Timer() as timer:
        try:
            data = process.read_bytes(address, length)
        except OSError as error:
            raise CommandError(
                f"Cannot read {length} byte(s) at 0x{address:X}: {error}"
            )

    session.printer.write(render_hexdump(data, address, width))
    session.printer.write()
    session.printer.ok(f"{len(data)} bytes", elapsed=timer.elapsed)
    session.printer.write()


@command(
    "watch",
    summary="Poll an address and print it as it changes.",
    usage="watch <address> [type] [length] [--interval S] [--count N] [--all]",
    group="Memory",
    details=(
        "Reads the address on a timer and prints a line per sample. By default "
        "only samples whose value differs from the previous one are printed, "
        "which turns the terminal into a change log; --all prints every "
        "sample.\n\n"
        "  --interval S  seconds between reads (default: the 'watch_interval'\n"
        "                setting)\n"
        "  --count N     stop after N samples; without it, watch runs until\n"
        "                Ctrl+C\n\n"
        "This is the terminal answer to a cheat table: leave it running in one "
        "window while the target does its thing."
    ),
    examples=(
        "watch game.exe+0x1234 int32",
        "watch [base+0x10]+0x8 float --interval 0.1",
        "watch #1 int32 --count 20 --all",
    ),
)
def cmd_watch(session: Session, args: List[str]) -> None:
    parser = CommandParser("watch")
    parser.add_argument("address")
    parser.add_argument("type", nargs="?", default=None)
    parser.add_argument("length", nargs="?", type=int, default=None)
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--all", action="store_true")
    options = parser.parse_args(args)

    process = session.require_process("watch")
    value_type = _resolve_type(options.type)
    width = value_type.read_width(options.length)
    address = parse_address(options.address, session)
    interval = (
        options.interval
        if options.interval is not None
        else float(session.option("watch_interval"))
    )
    if interval <= 0:
        raise CommandError("--interval must be greater than zero.")

    hex_output = bool(session.option("hex"))
    printer = session.printer
    printer.write(
        f"Watching {format_address(address, process.pointer_size)} as "
        f"{value_type.name} every {interval:g}s. Press Ctrl+C to stop."
    )

    samples = 0
    printed = 0
    previous = object()  # A sentinel no read can equal, so sample 1 always prints.

    try:
        while not options.count or samples < options.count:
            try:
                value = value_type.decode(
                    process.read_process_memory(address, value_type.pytype, width)
                )
            except OSError as error:
                printer.error(f"Read failed at 0x{address:X}: {error}")
                break

            samples += 1
            if options.all or value != previous:
                stamp = time.strftime("%H:%M:%S")
                printer.write(
                    f"{stamp}  {value_type.format(value, hex_output=hex_output)}"
                )
                printed += 1
                previous = value

            if options.count and samples >= options.count:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        # Ctrl+C is how a watch is meant to end, not an error.
        printer.write()

    printer.ok(f"{samples} sample(s), {printed} printed.")
    printer.write()


@command(
    "alloc",
    summary="Allocate memory inside the target.",
    usage="alloc <size> [--permission N]",
    group="Memory",
    details=(
        "Reserves and commits SIZE bytes in the target's address space and "
        "prints the base address. The region stays until 'free' releases it.\n\n"
        "  --permission N  platform-specific protection: a PAGE_* value on\n"
        "                  Windows (default PAGE_EXECUTE_READWRITE), a VM_PROT_*\n"
        "                  bitmask on macOS.\n\n"
        "Not available on Linux, which has no cross-process allocation syscall."
    ),
    examples=("alloc 4096", "alloc 0x1000"),
)
def cmd_alloc(session: Session, args: List[str]) -> None:
    parser = CommandParser("alloc")
    parser.add_argument("size")
    parser.add_argument("--permission", default=None)
    options = parser.parse_args(args)

    process = session.require_process("alloc")
    size = parse_int(options.size, "size")
    if size < 1:
        raise CommandError("Size must be at least 1 byte.")

    permission = (
        parse_int(options.permission, "permission")
        if options.permission is not None
        else None
    )

    with Timer() as timer:
        try:
            address = process.allocate_memory(size, permission=permission)
        except NotImplementedError:
            raise CommandError(
                "Allocating inside another process is not supported on this "
                "platform (Linux has no cross-process allocation syscall)."
            )
        except OSError as error:
            raise CommandError(f"Allocation failed: {error}")

    session.invalidate()
    session.printer.ok(
        f"Allocated {format_size(size)} at "
        f"{format_address(address, process.pointer_size)}.",
        elapsed=timer.elapsed,
    )
    session.printer.write()


@command(
    "free",
    summary="Release memory allocated with 'alloc'.",
    usage="free <address> [size]",
    group="Memory",
    details=(
        "The size may be omitted for a region this session allocated — "
        "PyMemoryEditor remembers it. Give one only to free a region it did "
        "not allocate."
    ),
    examples=("free 0x7ffee3a01000", "free 0x7ffee3a01000 4096"),
)
def cmd_free(session: Session, args: List[str]) -> None:
    parser = CommandParser("free")
    parser.add_argument("address")
    parser.add_argument("size", nargs="?", default=None)
    options = parser.parse_args(args)

    process = session.require_process("free")
    address = parse_address(options.address, session)
    size = parse_int(options.size, "size") if options.size is not None else 0

    with Timer() as timer:
        try:
            freed = process.free_memory(address, size)
        except NotImplementedError:
            raise CommandError(
                "Freeing memory in another process is not supported on Linux."
            )
        except OSError as error:
            raise CommandError(f"Free failed: {error}")

    if not freed:
        raise CommandError(f"The kernel refused to free 0x{address:X}.")

    session.invalidate()
    session.printer.ok(f"Freed 0x{address:X}.", elapsed=timer.elapsed)
    session.printer.write()


__all__ = ()
