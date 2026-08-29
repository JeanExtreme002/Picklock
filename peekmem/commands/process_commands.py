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


@command(
    "ps",
    summary="List the processes visible to you.",
    usage="ps [pattern] [--pid-sort] [--case-sensitive] [--limit N]",
    group="Process",
    aliases=("processes", "list"),
    details=(
        "With no pattern, every visible process is listed. A pattern matches "
        "the process name as a case-insensitive substring, and also matches a "
        "PID exactly when it is all digits.\n\n"
        "Only processes your user can see are listed. Run Peekmem elevated to "
        "see (and open) processes belonging to other users."
    ),
    examples=("ps", "ps chrome", "ps --pid-sort --limit 50"),
)
def cmd_ps(session: Session, args: List[str]) -> None:
    parser = CommandParser("ps")
    parser.add_argument("pattern", nargs="?", default=None)
    parser.add_argument("--pid-sort", action="store_true", help="sort by PID")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    options = parser.parse_args(args)

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


@command(
    "open",
    summary="Attach to a process by PID or name.",
    usage="open <pid|name> [-i] [--partial] [--strict-bitness]",
    group="Process",
    aliases=("attach", "use"),
    details=(
        "An all-digits target is taken as a PID, anything else as a process "
        "name; force either reading with --pid or --name.\n\n"
        "  -i / --ignore-case  match the name regardless of case.\n"
        "  --partial           match the name as a substring ('chrome' finds\n"
        "                      'chrome.exe'). Fails when more than one process\n"
        "                      matches, listing the candidates.\n"
        "  --strict-bitness    refuse to attach when the target's 32/64-bit\n"
        "                      width cannot be determined, instead of guessing\n"
        "                      it from this interpreter. Worth using before a\n"
        "                      pointer scan, where a wrong width is silent.\n\n"
        "Attaching replaces any previous target and clears the scan results."
    ),
    examples=("open 4242", "open notepad.exe", "open chrome --partial -i"),
)
def cmd_open(session: Session, args: List[str]) -> None:
    parser = CommandParser("open")
    parser.add_argument("target", nargs="?", default=None)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("-i", "--ignore-case", action="store_true")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--strict-bitness", action="store_true")
    options = parser.parse_args(args)

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


@command(
    "close",
    summary="Detach from the current process.",
    usage="close",
    group="Process",
    aliases=("detach",),
    details=(
        "Closes the OS handle and drops the scan results, the pointer paths "
        "and the cached memory map. The target itself is untouched — nothing "
        "Peekmem wrote to it is undone."
    ),
)
def cmd_close(session: Session, args: List[str]) -> None:
    CommandParser("close").parse_args(args)
    if not session.detach():
        raise CommandError("No process attached.")
    session.printer.ok("Detached.")


@command(
    "status",
    summary="Show the session state and versions.",
    usage="status",
    group="Process",
    aliases=("\\s",),
    details="Cheap: reports what the session knows without touching the target.",
)
def cmd_status(session: Session, args: List[str]) -> None:
    CommandParser("status").parse_args(args)

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


@command(
    "info",
    summary="Describe the attached process in detail.",
    usage="info",
    group="Process",
    details=(
        "Enumerates the memory map to report how much of the address space is "
        "mapped, so it costs a little more than 'status'."
    ),
)
def cmd_info(session: Session, args: List[str]) -> None:
    CommandParser("info").parse_args(args)
    process = session.require_process("info")

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
