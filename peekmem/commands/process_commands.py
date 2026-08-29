# -*- coding: utf-8 -*-

"""Finding a target and attaching to it: ``ps``, ``open``, ``close``, ``info``."""

import platform
from typing import List

import PyMemoryEditor

from .. import __version__, processes
from ..errors import CommandError
from ..output import LEFT, RIGHT, Timer, format_size, render_vertical
from ..session import Session
from . import CommandParser, command


def _ps_parser() -> CommandParser:
    parser = CommandParser("process:list")
    parser.add_argument(
        "pattern",
        nargs="?",
        default=None,
        help="keep processes whose name contains this text; an all-digit "
        "pattern also matches that PID exactly",
    )
    parser.add_argument(
        "--pid-sort",
        action="store_true",
        help="sort by PID instead of by name",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="match the pattern case-sensitively",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="print at most N rows, overriding the 'limit' setting",
    )
    return parser


@command(
    "process:list",
    parser=_ps_parser,
    summary="List the processes visible to you.",
    usage="process:list [pattern] [--pid-sort] [--case-sensitive] [--limit N]",
    details=(
        "Only processes your user can see are listed. Run Peekmem elevated to "
        "see (and open) processes belonging to other users."
    ),
    examples=("process:list", "process:list chrome", "process:list --pid-sort --limit 50"),
)
def cmd_ps(session: Session, args: List[str]) -> None:
    options = _ps_parser().parse_args(args)

    with Timer() as timer:
        entries = processes.list_processes(
            options.pattern,
            case_sensitive=options.case_sensitive,
            sort_by="pid" if options.pid_sort else "name",
        )

    limit = session.display_limit(options.limit)
    shown = entries[:limit] if limit else entries

    session.printer.table(
        ("PID", "NAME"),
        # A blank name means the OS would not tell us — macOS does that for
        # some system processes. Print a placeholder so the column is never
        # mistaken for an empty string the process actually has.
        [(pid, name or "?") for pid, name in shown],
        (RIGHT, LEFT),
        elapsed=timer.elapsed,
        total=len(entries),
    )


def _open_parser() -> CommandParser:
    parser = CommandParser("process:open")
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="the PID (all digits) or the process name to attach to",
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        metavar="PID",
        help="attach by PID, when the target could be read either way",
    )
    parser.add_argument(
        "--name",
        default=None,
        metavar="NAME",
        help="attach by process name, when the name is all digits",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="match the name regardless of case",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="match the name case-sensitively (the default on Linux and macOS)",
    )
    parser.add_argument(
        "--partial",
        action="store_true",
        help="match the name as a substring ('chrome' finds 'chrome.exe'); "
        "fails when more than one process matches, listing the candidates",
    )
    parser.add_argument(
        "--strict-bitness",
        action="store_true",
        help="refuse to attach when the target's 32/64-bit width cannot be "
        "determined, instead of guessing it from this interpreter",
    )
    return parser


@command(
    "process:open",
    parser=_open_parser,
    summary="Attach to a process by PID or name.",
    usage="process:open <pid|name> [-i] [--partial] [--strict-bitness]",
    details=(
        "An all-digits target is taken as a PID, anything else as a process "
        "name; force either reading with --pid or --name.\n\n"
        "--strict-bitness is worth using before a pointer scan, where a wrong "
        "pointer width is silent rather than loud.\n\n"
        "Attaching replaces any previous target and clears the scan results."
    ),
    examples=("process:open 4242", "process:open notepad.exe", "process:open chrome --partial -i"),
)
def cmd_open(session: Session, args: List[str]) -> None:
    options = _open_parser().parse_args(args)

    pid, name = options.pid, options.name

    if options.target is not None:
        if pid is not None or name is not None:
            raise CommandError("Give a target, or --pid/--name — not both.")
        if options.target.isdigit():
            pid = int(options.target)
        else:
            name = options.target

    if pid is None and name is None:
        raise CommandError("open needs a PID or a process name.")

    case_sensitive = None
    if options.ignore_case:
        case_sensitive = False
    elif options.case_sensitive:
        case_sensitive = True

    with Timer() as timer:
        process = session.attach(
            pid=pid,
            name=name,
            case_sensitive=case_sensitive,
            exact_match=not options.partial,
            strict_bitness=options.strict_bitness,
        )

    label = session.process_name or "?"
    bitness = "64-bit" if process.is_64bit else "32-bit"
    if not process.is_bitness_certain:
        bitness += " (assumed)"

    session.printer.ok(
        f"Attached to {label} (PID {process.pid}, {bitness}).",
        elapsed=timer.elapsed,
    )


def _close_parser() -> CommandParser:
    return CommandParser("process:close")


@command(
    "process:close",
    parser=_close_parser,
    summary="Detach from the current process.",
    usage="process:close",
    details=(
        "Takes no arguments.\n\n"
        "Closes the OS handle and drops the scan results, the pointer paths "
        "and the cached memory map. The target itself is untouched — nothing "
        "Peekmem wrote to it is undone."
    ),
)
def cmd_close(session: Session, args: List[str]) -> None:
    _close_parser().parse_args(args)
    if not session.detach():
        raise CommandError("No process attached.")
    session.printer.ok("Detached.")


def _status_parser() -> CommandParser:
    return CommandParser("status")


@command(
    "status",
    parser=_status_parser,
    summary="Show the session state and versions.",
    usage="status",
    aliases=("\\s",),
    details=(
        "Takes no arguments.\n\n"
        "Cheap: reports what the session knows without touching the target."
    ),
)
def cmd_status(session: Session, args: List[str]) -> None:
    _status_parser().parse_args(args)

    rows = [
        ("Peekmem", __version__),
        ("PyMemoryEditor", PyMemoryEditor.__version__),
        ("Python", platform.python_version()),
        ("Platform", f"{platform.system()} {platform.release()} ({platform.machine()})"),
    ]

    if session.process is None:
        rows.append(("Process", "(none attached)"))
    else:
        rows.append(("Process", f"{session.process_name or '?'} (PID {session.process.pid})"))
        rows.append(("Architecture", "64-bit" if session.process.is_64bit else "32-bit"))

    if session.scan is not None:
        rows.append(
            (
                "Scan results",
                f"{len(session.scan)} address(es) — {session.scan.description}",
            )
        )
    if session.pointer_paths:
        rows.append(("Pointer paths", str(len(session.pointer_paths))))

    session.printer.write(render_vertical(rows))
    session.printer.write()


def _info_parser() -> CommandParser:
    return CommandParser("process:info")


@command(
    "process:info",
    parser=_info_parser,
    summary="Describe the attached process in detail.",
    usage="process:info",
    details=(
        "Takes no arguments.\n\n"
        "Enumerates the memory map to report how much of the address space is "
        "mapped, so it costs a little more than 'status'."
    ),
)
def cmd_info(session: Session, args: List[str]) -> None:
    _info_parser().parse_args(args)
    process = session.require_process("process:info")

    with Timer() as timer:
        regions = session.regions(refresh=True)
        mapped = sum(region.size for region in regions)
        writable = sum(region.size for region in regions if region.is_writable)
        executable = sum(region.size for region in regions if region.is_executable)

    main_thread = process.main_thread

    rows = [
        ("PID", process.pid),
        ("Name", session.process_name or "?"),
        ("Architecture", "64-bit" if process.is_64bit else "32-bit"),
        ("Bitness certain", "yes" if process.is_bitness_certain else "no (assumed)"),
        ("Pointer size", f"{process.pointer_size} bytes"),
        ("Regions", f"{len(regions)} ({format_size(mapped)} mapped)"),
        ("Writable", format_size(writable)),
        ("Executable", format_size(executable)),
        ("Main thread", main_thread.tid if main_thread else "unknown"),
    ]

    session.printer.write(render_vertical(rows))
    session.printer.write()
    if session.printer.timing:
        session.printer.ok(f"Memory map read in {timer.elapsed:.2f} sec.")
        session.printer.write()


__all__ = ()
