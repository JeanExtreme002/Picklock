# -*- coding: utf-8 -*-

"""
Finding an address: the scan / refine cycle.

The workflow is Cheat Engine's, typed instead of clicked. ``scan`` searches
the whole address space for a value and keeps every hit; ``next`` narrows that
set by comparing each address against a new value or against what it held
before; ``results`` shows where you are. Two or three rounds usually take a
few thousand candidates down to one.

Progress deserves a word. PyMemoryEditor reports scan progress alongside each
*match*, so a scan that finds nothing for ten seconds would report nothing at
all — indistinguishable from a hang in a terminal. Instead of relying on that,
the runner below feeds the library one batch of regions at a time and counts
the bytes itself, which gives a progress line that advances whether or not
anything is found, lets Ctrl+C interrupt a scan and keep the partial results,
and costs nothing: the library processes regions independently anyway, so
batching them changes no result.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

from PyMemoryEditor import MemoryRegion, ScanTypesEnum

from .. import valuetypes
from ..addressing import parse_int
from ..errors import CommandError
from ..output import LEFT, RIGHT, Timer, format_address
from ..session import ScanState, Session
from ..valuetypes import ValueType
from . import CommandParser, add_paging_arguments, command, paginate

#: Bytes of address space handed to the library per call. Large enough that
#: per-call overhead is noise next to the scan itself, small enough that the
#: progress line moves and Ctrl+C lands promptly.
_BATCH_BYTES = 64 * 1024 * 1024

#: Command-line comparison names, and the symbols people type instead.
#: Comparisons that take a value you supply. Flags, not a keyword sitting in
#: the same slot a value would: 'scan:next changed' could not tell a comparison
#: from a search for the word "changed", and no amount of documentation fixes
#: an ambiguity the grammar has.
_VALUE_FLAGS = (
    ("eq", "keep values equal to VALUE — the same as giving VALUE on its own"),
    ("ne", "keep values different from VALUE"),
    ("gt", "keep values greater than VALUE"),
    ("lt", "keep values smaller than VALUE"),
    ("ge", "keep values greater than or equal to VALUE"),
    ("le", "keep values smaller than or equal to VALUE"),
)

#: The two that take a pair.
_RANGE_FLAGS = (
    ("between", "keep values inside the range A..B, inclusive"),
    ("not-between", "keep values outside the range A..B"),
)

#: Comparisons only a refine can make, against the value the last scan read.
_REFINE_FLAGS = (
    ("changed", 0, "keep addresses whose value differs from the last reading"),
    ("unchanged", 0, "keep addresses whose value equals the last reading"),
    ("increased", 0, "keep addresses whose value grew since the last reading"),
    ("decreased", 0, "keep addresses whose value shrank since the last reading"),
    ("increased-by", 1, "keep addresses that grew by exactly VALUE"),
    ("decreased-by", 1, "keep addresses that shrank by exactly VALUE"),
)

#: The library scan type each value comparison maps to.
_SCAN_TYPE = {
    "eq": ScanTypesEnum.EXACT_VALUE,
    "ne": ScanTypesEnum.NOT_EXACT_VALUE,
    "gt": ScanTypesEnum.BIGGER_THAN,
    "lt": ScanTypesEnum.SMALLER_THAN,
    "ge": ScanTypesEnum.BIGGER_THAN_OR_EXACT_VALUE,
    "le": ScanTypesEnum.SMALLER_THAN_OR_EXACT_VALUE,
}

_MAX_HELP = "stop after N hits, overriding the 'max_results' setting"


def _add_comparison_flags(parser: CommandParser, *, refine: bool) -> CommandParser:
    """Give a scan the comparison flags, declared once for both of them."""
    group = parser.add_mutually_exclusive_group()
    for name, help_text in _VALUE_FLAGS:
        group.add_argument(f"--{name}", metavar="VALUE", default=None, help=help_text)
    for name, help_text in _RANGE_FLAGS:
        group.add_argument(
            f"--{name}", nargs=2, metavar=("A", "B"), default=None, help=help_text
        )
    if refine:
        for name, arity, help_text in _REFINE_FLAGS:
            if arity:
                group.add_argument(
                    f"--{name}", metavar="VALUE", default=None, help=help_text
                )
            else:
                group.add_argument(f"--{name}", action="store_true", help=help_text)
    return parser


def _comparison(options, positional, *, refine: bool) -> Tuple[str, List[str]]:
    """Which comparison was asked for, and the words it was given.

    A bare value means equality, which is what a scan almost always is. Every
    other comparison is named by its flag, so the value slot only ever holds a
    value.
    """
    names = [name for name, _ in _VALUE_FLAGS] + [name for name, _ in _RANGE_FLAGS]
    if refine:
        names += [name for name, _, _ in _REFINE_FLAGS]

    for name in names:
        given = getattr(options, name.replace("-", "_"))
        if given is None or given is False:
            continue
        if positional is not None:
            raise CommandError(
                f"Give a value or --{name}, not both — '--{name}' already says "
                "what to compare."
            )
        operands = [] if given is True else list(given) if isinstance(given, list) else [given]
        return name, operands

    if positional is None:
        listed = ", ".join(f"--{name}" for name, _ in _VALUE_FLAGS[:3])
        raise CommandError(
            f"Nothing to compare against. Give a value, or one of {listed}, … "
            "— the full list is in the help."
        )
    return "eq", [positional]


def _batch_regions(
    regions: Sequence[MemoryRegion], budget: int = _BATCH_BYTES
) -> Iterable[Tuple[List[MemoryRegion], int]]:
    """Group regions into roughly ``budget``-sized batches, in address order."""
    batch: List[MemoryRegion] = []
    size = 0
    for region in regions:
        batch.append(region)
        size += region.size
        if size >= budget:
            yield batch, size
            batch, size = [], 0
    if batch:
        yield batch, size


@dataclass
class ScanOutcome:
    """What a scan found, and everything that got in its way.

    A scan is long and the address space is a moving target, so "it worked" and
    "it failed" are not the only two answers. Each of these flags means the
    results are real but partial, and every one of them is reported to the user
    rather than quietly folded into the row count.
    """

    addresses: List[int] = field(default_factory=list)
    #: The ``max_results`` cap stopped the scan early.
    truncated: bool = False
    #: Ctrl+C stopped it.
    interrupted: bool = False
    #: Batches of regions the backend refused to read.
    skipped: int = 0
    #: The last such refusal, for the note that reports them.
    last_error: Optional[BaseException] = None


def _run_scan(
    session: Session,
    search: Callable[[List[MemoryRegion]], Iterable[Any]],
    *,
    label: str = "Scanning",
    max_results: Optional[int] = None,
    writable_only: Optional[bool] = None,
) -> ScanOutcome:
    """Drive ``search`` over the target's regions.

    :param search: called with a batch of regions, yields matching addresses.
    :param max_results: cap for this scan only, from ``--max``. Without it the
        ``max_results`` setting applies. It is an argument rather than a write
        to the setting so that capping one scan does not quietly cap every
        scan after it.
    :param writable_only: which regions to walk, once ``--writable`` and
        ``--all-regions`` have had their say. Without it the ``writable_only``
        setting decides — which is why it has to be passed: the setting alone
        would filter the regions before ``--all-regions`` could widen them.

    Nothing here throws away results it already has. Ctrl+C stops the scan and
    keeps them, because punishing an impatient keystroke by discarding four
    minutes of scanning helps nobody. A read failure skips the rest of that
    batch and moves to the next one, for the same reason and one more: a page
    that cannot be read is ordinary weather in another process's address
    space — it may have been unmapped a microsecond ago, or be file-backed and
    declined by its pager — and it says nothing about the thousands of regions
    behind it. Both are reported; neither is silent.
    """
    regions = session.scan_regions(writable_only=writable_only)
    total = sum(region.size for region in regions) or 1
    if max_results is None:
        max_results = int(session.option("max_results"))
    show_progress = bool(session.option("progress"))
    printer = session.printer

    outcome = ScanOutcome()
    scanned = 0

    try:
        for batch, batch_size in _batch_regions(regions):
            try:
                for address in search(batch):
                    outcome.addresses.append(address)
                    if max_results and len(outcome.addresses) >= max_results:
                        outcome.truncated = True
                        break
            except OSError as error:
                # The backend gave up on this batch. Matches it had already
                # yielded are kept; the rest of the address space is still
                # worth walking.
                outcome.skipped += 1
                outcome.last_error = error

            scanned += batch_size
            if show_progress:
                printer.progress(label, scanned / total)
            if outcome.truncated:
                break
    except KeyboardInterrupt:
        outcome.interrupted = True
    finally:
        printer.clear_progress()

    return outcome


def _read_values(
    session: Session,
    value_type: ValueType,
    width: int,
    addresses: Sequence[int],
) -> List[Any]:
    """Read the current value at each address, in one chunked pass.

    ``search_by_addresses`` walks the region snapshot once and slices every
    requested address out of it, which is dramatically cheaper than one read
    call per address when there are thousands of them. Addresses it cannot
    read come back as ``None`` and stay ``None`` here — the caller decides
    whether that drops the row.
    """
    if not addresses:
        return []
    process = session.require_process()
    ordered = sorted(addresses)
    found = dict(
        process.search_by_addresses(
            value_type.pytype,
            width,
            ordered,
            memory_regions=session.regions(),
        )
    )
    return [value_type.decode(found.get(address)) for address in addresses]


#: Said whenever a result set that skipped read-only memory is shown. A scan
#: that quietly searched a tenth of the address space is the kind of thing you
#: work out an hour later, from an address that should have been found and was
#: not.
_WRITABLE_ONLY = (
    "Writable regions only — nothing in read-only memory was searched. "
    "Use '--all-regions' on the first scan to include it."
)


def _store(
    session: Session,
    value_type: ValueType,
    width: int,
    addresses: Sequence[int],
    description: str,
    *,
    truncated: bool,
    writable_only: bool = False,
) -> ScanState:
    values = _read_values(session, value_type, width, addresses)
    return session.store_scan(
        value_type,
        width,
        addresses,
        values,
        description,
        truncated=truncated,
        writable_only=writable_only,
    )


def _report(
    session: Session,
    state: ScanState,
    elapsed: float,
    outcome: ScanOutcome,
    *,
    limit: Optional[int] = None,
) -> None:
    """Print the outcome of a scan: any caveats, then a preview table."""
    printer = session.printer

    if outcome.interrupted:
        printer.note("Interrupted — showing what had been found so far.")
    if state.truncated:
        printer.note(
            f"Stopped at the cap of {len(state.addresses)} results. "
            "Narrow the scan, or raise it with '--max N' for one scan or "
            "'config:set max_results N' for all of them."
        )
    if outcome.skipped:
        printer.note(
            f"Skipped {outcome.skipped} batch(es) of regions the target would "
            f"not let us read — the last failure was: {outcome.last_error}. "
            "The rest of the address space was scanned normally."
        )

    _print_results(session, state, limit=limit, elapsed=elapsed)


def _print_results(
    session: Session,
    state: ScanState,
    *,
    limit: Optional[int] = None,
    elapsed: Optional[float] = None,
    number: int = 1,
) -> None:
    """Print the result set, one page at a time.

    The next page is fetched with ``scan:results``, not by re-running the scan
    — which is why the hint names that command whatever produced the rows.
    """
    if state.writable_only:
        session.printer.note(_WRITABLE_ONLY)

    process = session.require_process()
    hex_output = bool(session.option("hex"))
    indexes = range(len(state.addresses))
    page = paginate(
        session, indexes, command="scan:results", limit=limit, page=number
    )

    rows = [
        (
            f"#{index + 1}",
            format_address(state.addresses[index], process.pointer_size),
            state.value_type.format(state.values[index], hex_output=hex_output),
        )
        for index in page.rows
    ]

    session.printer.table(
        ("ROW", "ADDRESS", "VALUE"),
        rows,
        (RIGHT, LEFT, LEFT),
        elapsed=elapsed,
        total=page.total,
        page=page.number,
        pages=page.count,
        next_page=page.next_page,
    )


def _scan_parser() -> CommandParser:
    parser = CommandParser("scan:value")
    parser.add_argument("type", help="value type to search for (see 'help types')")
    parser.add_argument(
        "value",
        nargs="?",
        default=None,
        help="the value to search for; the same as --eq VALUE",
    )
    _add_comparison_flags(parser, refine=False)
    parser.add_argument(
        "--writable",
        action="store_true",
        help="scan only writable regions — much faster, and where a changing "
        "value almost always lives",
    )
    parser.add_argument(
        "--all-regions",
        action="store_true",
        help="scan everything, overriding the 'writable_only' setting",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=None,
        metavar="N",
        help="buffer width for string/bytes scans",
    )
    parser.add_argument("--max", type=int, default=None, metavar="N", help=_MAX_HELP)
    return parser


@command(
    "scan:value",
    parser=_scan_parser,
    summary="Search the whole address space for a value.",
    details=(
        "The first scan of a cycle. Every matching address is kept as the "
        "result set that 'scan:next', 'scan:results' and the '#N' address form "
        "work on.\n\n"
        "A bare value means equality, which is what a scan almost always is; "
        "every other comparison is named by its flag, so the value slot only "
        "ever holds a value.\n\n"
        "Ctrl+C stops a scan and keeps what it had already found."
    ),
    examples=(
        "scan:value int32 100",
        "scan:value float 99.5 --writable",
        "scan:value int32 --between 100 200",
        "scan:value string Picklock",
        "scan:value int32 --gt 1000",
    ),
)
def cmd_scan(session: Session, args: List[str]) -> None:
    options = _scan_parser().parse_args(args)

    process = session.require_process("scan:value")
    value_type = valuetypes.resolve(options.type)
    comparison, operands = _comparison(options, options.value, refine=False)

    if options.writable and options.all_regions:
        raise CommandError("--writable and --all-regions contradict each other.")
    writable_only = (
        True if options.writable
        else False if options.all_regions
        else bool(session.option("writable_only"))
    )

    # Refresh the map before a first scan: the target has probably allocated
    # since the last one, and a stale snapshot would silently skip new regions.
    session.regions(refresh=True)

    if comparison in ("between", "not-between"):
        start = value_type.parse(operands[0])
        end = value_type.parse(operands[1])
        width = max(
            value_type.width_for(start, options.length),
            value_type.width_for(end, options.length),
        )
        outside = comparison == "not-between"
        description = (
            f"{value_type.name} {'outside' if outside else 'between'} "
            f"{operands[0]} and {operands[1]}"
        )

        def search(batch: List[MemoryRegion]) -> Iterable[Any]:
            return process.search_by_value_between(
                value_type.pytype,
                width,
                value_type.encode(start),
                value_type.encode(end),
                not_between=outside,
                writeable_only=writable_only,
                memory_regions=batch,
            )

    else:
        value = value_type.parse(operands[0])
        width = value_type.width_for(value, options.length)
        scan_type = _SCAN_TYPE[comparison]
        description = f"{value_type.name} {comparison} {operands[0]}"

        def search(batch: List[MemoryRegion]) -> Iterable[Any]:
            return process.search_by_value(
                value_type.pytype,
                width,
                value_type.encode(value),
                scan_type,
                writeable_only=writable_only,
                memory_regions=batch,
            )

    with Timer() as timer:
        outcome = _run_scan(
            session, search, max_results=options.max, writable_only=writable_only
        )
        state = _store(
            session,
            value_type,
            width,
            outcome.addresses,
            description,
            truncated=outcome.truncated,
            writable_only=writable_only,
        )

    _report(session, state, timer.elapsed, outcome)


def _next_parser() -> CommandParser:
    parser = CommandParser("scan:next")
    parser.add_argument(
        "value",
        nargs="?",
        default=None,
        help="the value to keep; the same as --eq VALUE",
    )
    return _add_comparison_flags(parser, refine=True)


@command(
    "scan:next",
    parser=_next_parser,
    summary="Narrow the results with another comparison.",
    details=(
        "Re-reads every address in the result set and keeps the ones that "
        "still match. A bare value means equality: 'scan:next 95' keeps the "
        "addresses now holding 95.\n\n"
        "The comparisons that need no value of their own are for when you "
        "cannot see it — a health bar with no number. They measure each "
        "address against what the last scan read there, so making the value "
        "move in the target and then asking for '--decreased' narrows the set "
        "without you ever knowing the number.\n\n"
        "Addresses that have become unreadable (the target freed them) are "
        "dropped."
    ),
    examples=(
        "scan:next 95",
        "scan:next --changed",
        "scan:next --decreased",
        "scan:next --gt 50",
        "scan:next --between 10 20",
    ),
)
def cmd_next(session: Session, args: List[str]) -> None:
    options = _next_parser().parse_args(args)

    state = session.require_scan()
    session.require_process("scan:next")

    comparison, operands = _comparison(options, options.value, refine=True)
    value_type = state.value_type

    low = high = target = None
    if comparison in ("between", "not-between"):
        low = value_type.parse(operands[0])
        high = value_type.parse(operands[1])
    elif operands:
        target = value_type.parse(operands[0])

    with Timer() as timer:
        current = _read_values(session, value_type, state.width, state.addresses)

        kept_addresses: List[int] = []
        kept_values: List[Any] = []

        for address, previous, now in zip(state.addresses, state.values, current):
            if now is None:
                continue  # The address is gone; it cannot match anything.
            try:
                if comparison == "eq":
                    keep = now == target
                elif comparison == "ne":
                    keep = now != target
                elif comparison == "gt":
                    keep = now > target
                elif comparison == "lt":
                    keep = now < target
                elif comparison == "ge":
                    keep = now >= target
                elif comparison == "le":
                    keep = now <= target
                elif comparison == "between":
                    keep = low <= now <= high
                elif comparison == "not-between":
                    keep = not (low <= now <= high)
                elif comparison == "changed":
                    keep = now != previous
                elif comparison == "unchanged":
                    keep = now == previous
                elif comparison == "increased":
                    keep = previous is not None and now > previous
                elif comparison == "decreased":
                    keep = previous is not None and now < previous
                elif comparison == "increased-by":
                    keep = previous is not None and now == previous + target
                else:  # decreased-by
                    keep = previous is not None and now == previous - target
            except TypeError:
                # Ordering comparisons are meaningless for some type pairs
                # (a string against a number); treat that as "does not match"
                # rather than aborting a refine over one odd address.
                keep = False

            if keep:
                kept_addresses.append(address)
                kept_values.append(now)

        description = f"{state.description} → {comparison}"
        if operands:
            description += " " + " ".join(operands)

        new_state = session.store_scan(
            value_type,
            state.width,
            kept_addresses,
            kept_values,
            description,
            # A refine narrows what the first scan found, so it inherits what
            # that scan never looked at.
            writable_only=state.writable_only,
        )

    _print_results(session, new_state, elapsed=timer.elapsed)


def _aob_parser() -> CommandParser:
    parser = CommandParser("scan:aob")
    parser.add_argument(
        "pattern",
        help="IDA-style signature: hex bytes separated by spaces, with '?' or "
        "'??' for any single byte. Quote it, since it contains spaces",
    )
    parser.add_argument("--max", type=int, default=None, metavar="N", help=_MAX_HELP)
    return parser


@command(
    "scan:aob",
    parser=_aob_parser,
    summary="Scan for a byte pattern with wildcards (AOB).",
    details=(
        "This is how you find code that moves between builds: the opcodes stay "
        "put while the operands change, so you wildcard the operands. The "
        "result set holds the address of each match and can be refined with "
        "'scan:next' or read with 'memory:read #1'."
    ),
    examples=('scan:aob "48 8B ? ? 00 00"', 'scan:aob "DE AD BE EF"'),
)
def cmd_aob(session: Session, args: List[str]) -> None:
    options = _aob_parser().parse_args(args)

    process = session.require_process("scan:aob")

    from PyMemoryEditor.util.pattern import compile_pattern

    try:
        _, width = compile_pattern(options.pattern)
    except ValueError as error:
        raise CommandError(
            f"{error} Use IDA syntax: hex bytes separated by spaces, with '?' "
            "as a one-byte wildcard, e.g. '48 8B ? ? 00'."
        )

    session.regions(refresh=True)

    def search(batch: List[MemoryRegion]) -> Iterable[Any]:
        return process.search_by_pattern(options.pattern, memory_regions=batch)

    value_type = valuetypes.resolve("bytes")

    with Timer() as timer:
        outcome = _run_scan(session, search, label="AOB scan", max_results=options.max)
        state = _store(
            session,
            value_type,
            width,
            outcome.addresses,
            f"aob {options.pattern}",
            truncated=outcome.truncated,
            writable_only=bool(session.option("writable_only")),
        )

    _report(session, state, timer.elapsed, outcome)


def _regex_parser() -> CommandParser:
    parser = CommandParser("scan:regex")
    parser.add_argument(
        "pattern",
        help="a regular expression, UTF-8 encoded and matched against raw memory",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=64,
        metavar="N",
        help="the widest match to expect, in bytes (default 64); also how "
        "many bytes are read back for the VALUE column",
    )
    parser.add_argument("--max", type=int, default=None, metavar="N", help=_MAX_HELP)
    return parser


@command(
    "scan:regex",
    parser=_regex_parser,
    summary="Scan for text matching a regular expression.",
    details=(
        "Because the match runs over *bytes*, a metacharacter spans one byte: "
        "'.' matches any single byte and '\\d' is ASCII-only, so quantify with "
        "care around non-ASCII text.\n\n"
        "A regex has no fixed width, which is why --length matters: it is what "
        "lets a match straddling an internal chunk boundary still be found."
    ),
    examples=(
        'scan:regex "Player[0-9]+"',
        'scan:regex "https?://[a-z.]+" --length 128',
    ),
)
def cmd_regex(session: Session, args: List[str]) -> None:
    options = _regex_parser().parse_args(args)

    process = session.require_process("scan:regex")

    if options.length < 1:
        raise CommandError("--length must be at least 1 byte.")

    import re

    pattern = options.pattern.encode("utf-8")
    try:
        re.compile(pattern, re.DOTALL)
    except re.error as error:
        raise CommandError(f"Invalid regex: {error}")

    session.regions(refresh=True)

    def search(batch: List[MemoryRegion]) -> Iterable[Any]:
        return process.search_by_pattern(
            pattern, byte_length=options.length, memory_regions=batch
        )

    # The hits are text, so report them as a string of the requested width —
    # a hex dump of a matched URL helps nobody.
    value_type = valuetypes.resolve("string")

    with Timer() as timer:
        outcome = _run_scan(session, search, label="Regex scan", max_results=options.max)
        state = _store(
            session,
            value_type,
            options.length,
            outcome.addresses,
            f"regex {options.pattern}",
            truncated=outcome.truncated,
            writable_only=bool(session.option("writable_only")),
        )

    _report(session, state, timer.elapsed, outcome)


def _results_parser() -> CommandParser:
    parser = CommandParser("scan:results")
    parser.add_argument(
        "--export",
        default=None,
        metavar="FILE",
        help="write every result to a JSON file instead of paging through them",
    )
    return add_paging_arguments(parser)


def _export_results(session: Session, state: ScanState, path: str) -> int:
    """Write the whole result set to ``path`` as JSON, and say how many.

    Every row, not the page on screen: an export exists precisely for the
    results too numerous to read. Addresses are hex strings, the same shape
    PyMemoryEditor writes pointer paths in, and the scan's type and width ride
    along so the file says what the numbers in it mean.
    """
    process = session.require_process()
    values = _read_values(session, state.value_type, state.width, state.addresses)

    document = {
        "process": {"pid": process.pid, "name": session.process_name or None},
        "scan": state.description,
        "type": state.value_type.name,
        "width": state.width,
        "results": [
            {"address": "0x%X" % address, "value": _exportable(state, value)}
            for address, value in zip(state.addresses, values)
        ],
    }

    try:
        with open(path, "w", encoding="utf-8") as handle:
            # ensure_ascii=False: the file is UTF-8 and meant to be read, and
            # a description like "int32 eq 100 → changed" should say that
            # rather than "\u2192". Every JSON parser handles both; only one
            # of them is legible.
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError as error:
        raise CommandError(f"Cannot write {path!r}: {error}")

    return len(state.addresses)


def _exportable(state: ScanState, value) -> Any:
    """A value JSON can hold, without inventing precision it does not have.

    Numbers and booleans go through as themselves so a consumer can do
    arithmetic on them. Bytes have no JSON form, so they take the same hex
    spelling the table shows, and an address that could not be read stays
    null rather than becoming a zero somebody might trust.
    """
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    return state.value_type.format(value)


@command(
    "scan:results",
    parser=_results_parser,
    summary="Show the current result set, re-read.",
    details=(
        "Reads every address again, so the VALUE column is what the target "
        "holds now, not what it held when the scan ran. The PREVIOUS column "
        "shows the value the last scan recorded — the one 'scan:next changed' and "
        "friends compare against — and is filled in only where the two "
        "differ.\n\n"
        "Row numbers are what '#N' refers to in an address, and they keep "
        "counting across pages: row #21 is the first on page 2 of twenty.\n\n"
        "--export writes every result to a JSON file — all of them, not the "
        "page on screen — with the scan's type and width alongside, so the "
        "file says what its numbers mean."
    ),
    examples=(
        "scan:results",
        "scan:results --all",
        "scan:results --page 3 --limit 10",
        "scan:results --export found.json",
    ),
)
def cmd_results(session: Session, args: List[str]) -> None:
    options = _results_parser().parse_args(args)

    state = session.require_scan()
    process = session.require_process("scan:results")
    hex_output = bool(session.option("hex"))

    if options.export is not None:
        with Timer() as timer:
            written = _export_results(session, state, options.export)
        session.printer.ok(
            f"Wrote {written} result(s) to {options.export}.", elapsed=timer.elapsed
        )
        session.printer.write()
        return

    if state.writable_only:
        session.printer.note(_WRITABLE_ONLY)

    page = paginate(
        session,
        range(len(state.addresses)),
        command="scan:results",
        limit=options.limit,
        page=options.page,
        show_all=options.all,
    )
    window = list(page.rows)

    with Timer() as timer:
        current = _read_values(
            session,
            state.value_type,
            state.width,
            [state.addresses[index] for index in window],
        )

    rows = []
    for position, index in enumerate(window):
        now = current[position]
        previous = state.values[index]
        rows.append(
            (
                f"#{index + 1}",
                format_address(state.addresses[index], process.pointer_size),
                state.value_type.format(now, hex_output=hex_output),
                ""
                if now == previous
                else state.value_type.format(previous, hex_output=hex_output),
            )
        )

    session.printer.table(
        ("ROW", "ADDRESS", "VALUE", "PREVIOUS"),
        rows,
        (RIGHT, LEFT, LEFT, LEFT),
        elapsed=timer.elapsed,
        total=page.total,
        page=page.number,
        pages=page.count,
        next_page=page.next_page,
    )


def _parse_row_selection(tokens: Sequence[str], count: int) -> List[int]:
    """Turn ``['1', '3-5', '#9']`` into zero-based row indexes."""
    selected: List[int] = []
    for token in tokens:
        piece = token.strip().lstrip("#")
        if "-" in piece:
            low_text, _, high_text = piece.partition("-")
            low = parse_int(low_text, "row number")
            high = parse_int(high_text, "row number")
            if low > high:
                raise CommandError(f"Range {token!r} runs backwards.")
            candidates = range(low, high + 1)
        else:
            number = parse_int(piece, "row number")
            candidates = range(number, number + 1)

        for number in candidates:
            if not 1 <= number <= count:
                raise CommandError(
                    f"Row #{number} is out of range — there are {count} result(s)."
                )
            selected.append(number - 1)

    if not selected:
        raise CommandError("Name at least one row, e.g. 'scan:keep 1 3-5'.")
    return selected


_ROWS_HELP = "row numbers from 'results', singly or as ranges: 1 4 7-9 (a '#' prefix is optional)"


def _keep_parser() -> CommandParser:
    parser = CommandParser("scan:keep")
    parser.add_argument("rows", nargs="+", metavar="row", help=_ROWS_HELP)
    return parser


@command(
    "scan:keep",
    parser=_keep_parser,
    summary="Keep only the named result rows.",
    details=(
        "Use it when you can see which candidates are real and would rather "
        "not invent a comparison that happens to exclude the others."
    ),
    examples=("scan:keep 1", "scan:keep 1 3 7-9"),
)
def cmd_keep(session: Session, args: List[str]) -> None:
    options = _keep_parser().parse_args(args)
    state = session.require_scan()
    session.require_process("scan:keep")
    indexes = _parse_row_selection(options.rows, len(state.addresses))
    ordered = sorted(set(indexes))

    new_state = session.store_scan(
        state.value_type,
        state.width,
        [state.addresses[index] for index in ordered],
        [state.values[index] for index in ordered],
        f"{state.description} → kept {len(ordered)} row(s)",
    )
    _print_results(session, new_state)


def _drop_parser() -> CommandParser:
    parser = CommandParser("scan:drop")
    parser.add_argument("rows", nargs="+", metavar="row", help=_ROWS_HELP)
    return parser


@command(
    "scan:drop",
    parser=_drop_parser,
    summary="Remove the named result rows.",
    details="The inverse of 'keep'. Ranges work the same way.",
    examples=("scan:drop 2", "scan:drop 5-12"),
)
def cmd_drop(session: Session, args: List[str]) -> None:
    options = _drop_parser().parse_args(args)
    state = session.require_scan()
    session.require_process("scan:drop")
    removed = set(_parse_row_selection(options.rows, len(state.addresses)))
    remaining = [index for index in range(len(state.addresses)) if index not in removed]

    new_state = session.store_scan(
        state.value_type,
        state.width,
        [state.addresses[index] for index in remaining],
        [state.values[index] for index in remaining],
        f"{state.description} → dropped {len(removed)} row(s)",
    )
    _print_results(session, new_state)


def _reset_parser() -> CommandParser:
    return CommandParser("scan:reset")


@command(
    "scan:reset",
    parser=_reset_parser,
    summary="Discard the current scan results.",
    details=(
        "Takes no arguments.\n\n"
        "Clears the result set so the next 'scan' starts a fresh cycle. The "
        "attached process is left alone."
    ),
)
def cmd_reset(session: Session, args: List[str]) -> None:
    _reset_parser().parse_args(args)
    count = len(session.scan) if session.scan else 0
    session.scan = None
    session.printer.ok(f"Discarded {count} result(s).")
    session.printer.write()


__all__ = ()
