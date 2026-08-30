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
from . import CommandParser, add_paging_arguments, command, paginate

#: The help text shared by every argument that takes an address expression.
_ADDRESS_HELP = (
    "address expression: a literal, module+offset, [pointer] or #N — "
    "see 'help address'"
)

#: The help text shared by every optional type argument.
_TYPE_HELP = "value type; defaults to int32 (see 'help types')"

#: The help text shared by the length argument of the variable-width types.
_LENGTH_HELP = "byte width, required for the 'string' and 'bytes' types"


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


def _regions_parser() -> CommandParser:
    parser = CommandParser("memory:regions")
    parser.add_argument(
        "--writable", action="store_true", help="keep only writable regions"
    )
    parser.add_argument(
        "--executable", action="store_true", help="keep only executable regions"
    )
    parser.add_argument(
        "--shared",
        action="store_true",
        help="keep only shared or file-backed mappings",
    )
    parser.add_argument(
        "--path",
        default=None,
        metavar="TEXT",
        help="keep regions whose backing file path contains TEXT",
    )
    parser.add_argument(
        "--at",
        default=None,
        metavar="ADDRESS",
        help="show only the region containing this address",
    )
    return add_paging_arguments(parser)


@command(
    "memory:regions",
    parser=_regions_parser,
    summary="List the target's mapped memory regions.",
    details=(
        "The memory map is re-read on every call, so it reflects allocations "
        "the target made since the last look.\n\n"
        "The PERMS column reads like /proc/<pid>/maps: rwx plus 's' for a "
        "shared/file-backed mapping or 'p' for a private one."
    ),
    examples=("memory:regions --writable", "memory:regions --at 0x7ffee3a01000", "memory:regions --path libc"),
)
def cmd_regions(session: Session, args: List[str]) -> None:
    options = _regions_parser().parse_args(args)

    process = session.require_process("memory:regions")

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

    page = paginate(
        session,
        regions,
        command="memory:regions",
        limit=options.limit,
        page=options.page,
        show_all=options.all,
    )
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
            for region in page.rows
        ],
        (LEFT, RIGHT, LEFT, LEFT),
        elapsed=timer.elapsed,
        total=page.total,
        page=page.number,
        pages=page.count,
        next_page=page.next_page,
    )


def _modules_parser() -> CommandParser:
    parser = CommandParser("memory:modules")
    parser.add_argument(
        "pattern",
        nargs="?",
        default=None,
        help="keep modules whose name or path contains this text",
    )
    return add_paging_arguments(parser)


@command(
    "memory:modules",
    parser=_modules_parser,
    summary="List the modules loaded in the target.",
    details=(
        "A module is the main executable or a shared library (.dll / .so / "
        ".dylib). Its BASE moves on every launch under ASLR, which is why an "
        "address is best written as 'module+offset' — see 'help address'.\n\n"
        "Running this command refreshes the module table the address parser "
        "uses, so run it after the target loads a library."
    ),
    examples=("memory:modules", "memory:modules libc"),
)
def cmd_modules(session: Session, args: List[str]) -> None:
    options = _modules_parser().parse_args(args)

    process = session.require_process("memory:modules")

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

    page = paginate(
        session,
        modules,
        command="memory:modules",
        limit=options.limit,
        page=options.page,
        show_all=options.all,
    )
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
            for module in page.rows
        ],
        (LEFT, LEFT, RIGHT, LEFT),
        elapsed=timer.elapsed,
        total=page.total,
        page=page.number,
        pages=page.count,
        next_page=page.next_page,
    )


def _threads_parser() -> CommandParser:
    parser = CommandParser("memory:threads")
    return add_paging_arguments(parser)


@command(
    "memory:threads",
    parser=_threads_parser,
    summary="List the target's threads.",
    details=(
        "STATE and PRIORITY are filled in only where the platform exposes them "
        "cheaply (Linux does; Windows and macOS leave them empty). The meaning "
        "of TID is platform-specific: a POSIX task id on Linux, a kernel "
        "thread id on Windows, a Mach port name on macOS."
    ),
)
def cmd_threads(session: Session, args: List[str]) -> None:
    options = _threads_parser().parse_args(args)

    process = session.require_process("memory:threads")

    with Timer() as timer:
        threads = list(process.get_threads())

    page = paginate(
        session,
        threads,
        command="memory:threads",
        limit=options.limit,
        page=options.page,
        show_all=options.all,
    )

    session.printer.table(
        ("TID", "STATE", "PRIORITY"),
        [
            (
                thread.tid,
                thread.state if thread.state is not None else "",
                thread.priority if thread.priority is not None else "",
            )
            for thread in page.rows
        ],
        (RIGHT, LEFT, RIGHT),
        elapsed=timer.elapsed,
        total=page.total,
        page=page.number,
        pages=page.count,
        next_page=page.next_page,
    )


def _read_parser() -> CommandParser:
    parser = CommandParser("memory:read")
    parser.add_argument("address", help=_ADDRESS_HELP)
    parser.add_argument("type", nargs="?", default=None, help=_TYPE_HELP)
    parser.add_argument("length", nargs="?", type=int, default=None, help=_LENGTH_HELP)
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        metavar="N",
        help="read N consecutive values, stepping by the type's width",
    )
    parser.add_argument(
        "--hex", action="store_true", help="print integers in hexadecimal"
    )
    return parser


@command(
    "memory:read",
    parser=_read_parser,
    summary="Read a typed value from an address.",
    details=(
        "The type defaults to int32. 'string' and 'bytes' need a length in "
        "bytes; the fixed-width types ignore one.\n\n"
        "The address is an expression — see 'help address' — so a pointer "
        "chain can be read in one go."
    ),
    examples=(
        "memory:read 0x7ffee3a01000",
        "memory:read game.exe+0x1234 int32",
        "memory:read [game.exe+0x1a2b3c]+0x18 float",
        "memory:read 0x7ffee3a01000 string 32",
        "memory:read #1 int32 --count 8",
    ),
)
def cmd_read(session: Session, args: List[str]) -> None:
    options = _read_parser().parse_args(args)

    process = session.require_process("memory:read")
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


def _write_parser() -> CommandParser:
    parser = CommandParser("memory:write")
    parser.add_argument("address", help=_ADDRESS_HELP)
    parser.add_argument("type", help="value type (see 'help types')")
    parser.add_argument(
        "value",
        help="the value to write, parsed according to the type: integers "
        "accept 0x/0o/0b prefixes, booleans accept true/false/on/off, 'bytes' "
        "takes hex ('DE AD BE EF') and 'string' takes the text verbatim",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=None,
        metavar="N",
        help="buffer width for string/bytes; defaults to the natural width "
        "of the value given",
    )
    parser.add_argument(
        "--null-terminated",
        action="store_true",
        help="append a NUL after a string, for C-string writes",
    )
    return parser


@command(
    "memory:write",
    parser=_write_parser,
    summary="Write a typed value to an address.",
    details=(
        "There is no confirmation and no undo. Writing into a live process can "
        "crash it — read the address first if you are not sure of it."
    ),
    examples=(
        "memory:write 0x7ffee3a01000 int32 100",
        "memory:write game.exe+0x1234 float 99.5",
        "memory:write #2 bytes 'DE AD BE EF'",
        "memory:write 0x7ffee3a01000 string Picklock --null-terminated",
    ),
)
def cmd_write(session: Session, args: List[str]) -> None:
    options = _write_parser().parse_args(args)

    process = session.require_process("memory:write")
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


def _dump_parser() -> CommandParser:
    parser = CommandParser("memory:dump")
    parser.add_argument("address", help=_ADDRESS_HELP)
    parser.add_argument(
        "length",
        nargs="?",
        default="256",
        help="number of bytes to read (default 256); hex accepted",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        metavar="N",
        help="bytes per line, overriding the 'dump_width' setting",
    )
    return parser


@command(
    "memory:dump",
    parser=_dump_parser,
    summary="Hex-dump a range of memory.",
    details=(
        "Prints the classic three-column layout: absolute address, hex bytes, "
        "printable ASCII.\n\n"
        "The read is a single call, so a range that crosses into an unmapped "
        "page fails as a whole rather than returning half the bytes."
    ),
    examples=("memory:dump 0x7ffee3a01000", "memory:dump game.exe+0x1000 512", "memory:dump #1 64 --width 8"),
)
def cmd_dump(session: Session, args: List[str]) -> None:
    options = _dump_parser().parse_args(args)

    process = session.require_process("memory:dump")
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


def _watch_parser() -> CommandParser:
    parser = CommandParser("memory:watch")
    parser.add_argument("address", help=_ADDRESS_HELP)
    parser.add_argument("type", nargs="?", default=None, help=_TYPE_HELP)
    parser.add_argument("length", nargs="?", type=int, default=None, help=_LENGTH_HELP)
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        metavar="S",
        help="seconds between reads, overriding the 'watch_interval' setting",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        metavar="N",
        help="stop after N samples; without it, watch runs until Ctrl+C",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="print every sample, not only the ones whose value changed",
    )
    return parser


@command(
    "memory:watch",
    parser=_watch_parser,
    summary="Poll an address and print it as it changes.",
    details=(
        "Reads the address on a timer and prints a line per sample. By default "
        "only samples whose value differs from the previous one are printed, "
        "which turns the terminal into a change log.\n\n"
        "This is the terminal answer to a cheat table: leave it running in one "
        "window while the target does its thing."
    ),
    examples=(
        "memory:watch game.exe+0x1234 int32",
        "memory:watch [base+0x10]+0x8 float --interval 0.1",
        "memory:watch #1 int32 --count 20 --all",
    ),
)
def cmd_watch(session: Session, args: List[str]) -> None:
    options = _watch_parser().parse_args(args)

    process = session.require_process("memory:watch")
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


def _alloc_parser() -> CommandParser:
    parser = CommandParser("memory:alloc")
    parser.add_argument(
        "size", help="number of bytes to allocate; hex accepted (e.g. 0x1000)"
    )
    parser.add_argument(
        "--permission",
        default=None,
        metavar="N",
        help="platform-specific protection: a PAGE_* value on Windows "
        "(default PAGE_EXECUTE_READWRITE), a VM_PROT_* bitmask on macOS",
    )
    return parser


@command(
    "memory:alloc",
    parser=_alloc_parser,
    summary="Allocate memory inside the target.",
    details=(
        "Reserves and commits SIZE bytes in the target's address space and "
        "prints the base address. The region stays until 'memory:free' releases "
        "it.\n\n"
        "Not available on Linux, which has no cross-process allocation syscall."
    ),
    examples=("memory:alloc 4096", "memory:alloc 0x1000"),
)
def cmd_alloc(session: Session, args: List[str]) -> None:
    options = _alloc_parser().parse_args(args)

    process = session.require_process("memory:alloc")
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


def _free_parser() -> CommandParser:
    parser = CommandParser("memory:free")
    parser.add_argument("address", help="base address returned by 'memory:alloc'")
    parser.add_argument(
        "size",
        nargs="?",
        default=None,
        help="region size; only needed to free a region this session did not "
        "allocate, since PyMemoryEditor remembers its own",
    )
    return parser


@command(
    "memory:free",
    parser=_free_parser,
    summary="Release memory allocated with 'memory:alloc'.",
    details="Not available on Linux, for the same reason as 'memory:alloc'.",
    examples=("memory:free 0x7ffee3a01000", "memory:free 0x7ffee3a01000 4096"),
)
def cmd_free(session: Session, args: List[str]) -> None:
    options = _free_parser().parse_args(args)

    process = session.require_process("memory:free")
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
