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

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

from PyMemoryEditor import MemoryRegion, ScanTypesEnum

from .. import valuetypes
from ..addressing import parse_int
from ..errors import CommandError
from ..output import LEFT, RIGHT, Timer, format_address
from ..session import ScanState, Session
from ..valuetypes import ValueType
from . import CommandParser, command

#: Bytes of address space handed to the library per call. Large enough that
#: per-call overhead is noise next to the scan itself, small enough that the
#: progress line moves and Ctrl+C lands promptly.
_BATCH_BYTES = 64 * 1024 * 1024

#: Command-line comparison names, and the symbols people type instead.
_SCAN_OPS = {
    "eq": ScanTypesEnum.EXACT_VALUE,
    "ne": ScanTypesEnum.NOT_EXACT_VALUE,
    "gt": ScanTypesEnum.BIGGER_THAN,
    "lt": ScanTypesEnum.SMALLER_THAN,
    "ge": ScanTypesEnum.BIGGER_THAN_OR_EXACT_VALUE,
    "le": ScanTypesEnum.SMALLER_THAN_OR_EXACT_VALUE,
}
_OP_SYMBOLS = {
    "=": "eq", "==": "eq", "!=": "ne", "<>": "ne",
    ">": "gt", "<": "lt", ">=": "ge", "<=": "le",
}

#: Refine-only comparisons, which need the value recorded by the last scan.
_REFINE_OPS = (
    "changed",
    "unchanged",
    "increased",
    "decreased",
    "increased-by",
    "decreased-by",
    "between",
)

_MAX_HELP = "stop after N hits, overriding the 'max_results' setting"


def _normalize_op(name: str) -> str:
    key = name.strip().lower()
    return _OP_SYMBOLS.get(key, key)


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
) -> ScanOutcome:
    """Drive ``search`` over the target's regions.

    :param search: called with a batch of regions, yields matching addresses.

    Nothing here throws away results it already has. Ctrl+C stops the scan and
    keeps them, because punishing an impatient keystroke by discarding four
    minutes of scanning helps nobody. A read failure skips the rest of that
    batch and moves to the next one, for the same reason and one more: a page
    that cannot be read is ordinary weather in another process's address
    space — it may have been unmapped a microsecond ago, or be file-backed and
    declined by its pager — and it says nothing about the thousands of regions
    behind it. Both are reported; neither is silent.
    """
    regions = session.scan_regions()
    total = sum(region.size for region in regions) or 1
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


def _store(
    session: Session,
    value_type: ValueType,
    width: int,
    addresses: Sequence[int],
    description: str,
    *,
    truncated: bool,
) -> ScanState:
    values = _read_values(session, value_type, width, addresses)
    return session.store_scan(
        value_type, width, addresses, values, description, truncated=truncated
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
            f"Stopped at the max_results cap ({session.option('max_results')}). "
            "Narrow the scan, or raise it with 'set max_results N'."
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
    limit: Optional[int],
    elapsed: Optional[float],
    offset: int = 0,
) -> None:
    process = session.require_process()
    hex_output = bool(session.option("hex"))
    display_limit = session.display_limit(limit)

    end = len(state.addresses) if display_limit is None else offset + display_limit
    rows = []
    for index in range(offset, min(end, len(state.addresses))):
        rows.append(
            (
                f"#{index + 1}",
                format_address(state.addresses[index], process.pointer_size),
                state.value_type.format(state.values[index], hex_output=hex_output),
            )
        )

    session.printer.table(
        ("ROW", "ADDRESS", "VALUE"),
        rows,
        (RIGHT, LEFT, LEFT),
        elapsed=elapsed,
        total=len(state.addresses),
    )


def _scan_parser() -> CommandParser:
    parser = CommandParser("scan:value")
    parser.add_argument("type", help="value type to search for (see 'help types')")
    parser.add_argument(
        "value",
        nargs="?",
        default=None,
        help="the value to search for; omit it when using --between",
    )
    # Deliberately no `choices=`: argparse would reject the symbol spellings
    # ('>' and friends) before _normalize_op ever sees them, and those are the
    # ones people reach for first. The check below reports them itself.
    parser.add_argument(
        "--op",
        default="eq",
        metavar="OP",
        help="comparison against the value: eq (default), ne, gt, lt, ge, le. "
        "The symbols =, !=, >, <, >=, <= are accepted too",
    )
    parser.add_argument(
        "--between",
        nargs=2,
        metavar=("A", "B"),
        default=None,
        help="keep values inside the range A..B, inclusive",
    )
    parser.add_argument(
        "--outside", action="store_true", help="invert --between"
    )
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
    usage="scan:value <type> [value] [--op OP] [--between A B] [--writable] [--max N]",
    details=(
        "The first scan of a cycle. Every matching address is kept as the "
        "result set that 'scan:next', 'scan:results' and the '#N' address form "
        "work "
        "on.\n\n"
        "Ctrl+C stops a scan and keeps what it had already found."
    ),
    examples=(
        "scan:value int32 100",
        "scan:value float 99.5 --writable",
        "scan:value int32 --between 100 200",
        "scan:value string Peekmem",
        "scan:value int32 1000 --op gt",
    ),
)
def cmd_scan(session: Session, args: List[str]) -> None:
    options = _scan_parser().parse_args(args)

    process = session.require_process("scan:value")
    value_type = valuetypes.resolve(options.type)

    if options.writable and options.all_regions:
        raise CommandError("--writable and --all-regions contradict each other.")
    writable_only = (
        True if options.writable
        else False if options.all_regions
        else bool(session.option("writable_only"))
    )
    if options.max is not None:
        session.set_option("max_results", str(options.max))

    # Refresh the map before a first scan: the target has probably allocated
    # since the last one, and a stale snapshot would silently skip new regions.
    session.regions(refresh=True)

    if options.between is not None:
        if options.value is not None:
            raise CommandError("Give a value or --between, not both.")
        start = value_type.parse(options.between[0])
        end = value_type.parse(options.between[1])
        width = max(
            value_type.width_for(start, options.length),
            value_type.width_for(end, options.length),
        )
        description = (
            f"{value_type.name} {'outside' if options.outside else 'between'} "
            f"{options.between[0]} and {options.between[1]}"
        )

        def search(batch: List[MemoryRegion]) -> Iterable[Any]:
            return process.search_by_value_between(
                value_type.pytype,
                width,
                value_type.encode(start),
                value_type.encode(end),
                not_between=options.outside,
                writeable_only=writable_only,
                memory_regions=batch,
            )

    else:
        if options.value is None:
            raise CommandError("scan needs a value, or --between A B.")
        operation = _normalize_op(options.op)
        if operation not in _SCAN_OPS:
            raise CommandError(
                f"Unknown comparison {options.op!r}. Use one of: "
                + ", ".join(_SCAN_OPS)
                + "."
            )
        value = value_type.parse(options.value)
        width = value_type.width_for(value, options.length)
        scan_type = _SCAN_OPS[operation]
        description = f"{value_type.name} {operation} {options.value}"

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
        outcome = _run_scan(session, search)
        state = _store(
            session,
            value_type,
            width,
            outcome.addresses,
            description,
            truncated=outcome.truncated,
        )

    _report(session, state, timer.elapsed, outcome)


def _next_parser() -> CommandParser:
    parser = CommandParser("scan:next")
    parser.add_argument(
        "op",
        nargs="?",
        default=None,
        help="the comparison to apply: eq, ne, gt, lt, ge, le, between, "
        "changed, unchanged, increased, decreased, increased-by, "
        "decreased-by. Omit it to mean eq",
    )
    parser.add_argument(
        "value",
        nargs="*",
        default=[],
        help="the value the comparison needs — two for 'between', one for the "
        "six ordinary comparisons and the *-by pair, none for the rest",
    )
    return parser


@command(
    "scan:next",
    parser=_next_parser,
    summary="Narrow the results with another comparison.",
    usage="scan:next [op] [value]",
    details=(
        "Re-reads every address in the result set and keeps the ones that "
        "still match. Bare 'scan:next 100' means 'scan:next eq 100'.\n\n"
        "Comparisons against a value you supply:\n\n"
        "  eq ne gt lt ge le VALUE      the usual six\n"
        "  between A B                  inside the range, inclusive\n"
        "  increased-by N               grew by exactly N since the last scan\n"
        "  decreased-by N               shrank by exactly N since the last scan\n\n"
        "Comparisons against the previous scan, for when you do not know the "
        "value — the health bar moved, but to what?\n\n"
        "  changed / unchanged          differs from / equals the last reading\n"
        "  increased / decreased        moved in that direction\n\n"
        "Addresses that have become unreadable (the target freed them) are "
        "dropped."
    ),
    examples=("scan:next 95", "scan:next changed", "scan:next decreased", "scan:next gt 50", "scan:next between 10 20"),
)
def cmd_next(session: Session, args: List[str]) -> None:
    options = _next_parser().parse_args(args)

    state = session.require_scan()
    session.require_process("scan:next")

    operation = _normalize_op(options.op) if options.op else "eq"
    operands = list(options.value)

    # "next 100" — no operation word, just a value. Recognised by the first
    # word not naming a comparison, which is unambiguous: no comparison name
    # is also a valid value spelling.
    if operation not in _SCAN_OPS and operation not in _REFINE_OPS:
        if options.op is None:
            raise CommandError("next needs a comparison or a value.")
        operands.insert(0, options.op)
        operation = "eq"

    value_type = state.value_type
    needs_value = operation in _SCAN_OPS or operation in (
        "increased-by",
        "decreased-by",
    )

    if operation == "between":
        if len(operands) != 2:
            raise CommandError(
                "'scan:next between' takes two values: scan:next between A B."
            )
        low = value_type.parse(operands[0])
        high = value_type.parse(operands[1])
    elif needs_value:
        if len(operands) != 1:
            raise CommandError(f"'scan:next {operation}' takes exactly one value.")
        target = value_type.parse(operands[0])
    elif operands:
        raise CommandError(f"'scan:next {operation}' takes no value.")

    with Timer() as timer:
        current = _read_values(session, value_type, state.width, state.addresses)

        kept_addresses: List[int] = []
        kept_values: List[Any] = []

        for address, previous, now in zip(state.addresses, state.values, current):
            if now is None:
                continue  # The address is gone; it cannot match anything.
            try:
                if operation == "eq":
                    keep = now == target
                elif operation == "ne":
                    keep = now != target
                elif operation == "gt":
                    keep = now > target
                elif operation == "lt":
                    keep = now < target
                elif operation == "ge":
                    keep = now >= target
                elif operation == "le":
                    keep = now <= target
                elif operation == "between":
                    keep = low <= now <= high
                elif operation == "changed":
                    keep = now != previous
                elif operation == "unchanged":
                    keep = now == previous
                elif operation == "increased":
                    keep = previous is not None and now > previous
                elif operation == "decreased":
                    keep = previous is not None and now < previous
                elif operation == "increased-by":
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

        description = f"{state.description} → {operation}"
        if operation == "between":
            description += f" {operands[0]} {operands[1]}"
        elif needs_value:
            description += f" {operands[0]}"

        new_state = session.store_scan(
            value_type,
            state.width,
            kept_addresses,
            kept_values,
            description,
        )

    _print_results(session, new_state, limit=None, elapsed=timer.elapsed)


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
    usage="scan:aob <pattern> [--max N]",
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

    if options.max is not None:
        session.set_option("max_results", str(options.max))
    session.regions(refresh=True)

    def search(batch: List[MemoryRegion]) -> Iterable[Any]:
        return process.search_by_pattern(options.pattern, memory_regions=batch)

    value_type = valuetypes.resolve("bytes")

    with Timer() as timer:
        outcome = _run_scan(session, search, label="AOB scan")
        state = _store(
            session,
            value_type,
            width,
            outcome.addresses,
            f"aob {options.pattern}",
            truncated=outcome.truncated,
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
    usage="scan:regex <pattern> [--length N] [--max N]",
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

    if options.max is not None:
        session.set_option("max_results", str(options.max))
    session.regions(refresh=True)

    def search(batch: List[MemoryRegion]) -> Iterable[Any]:
        return process.search_by_pattern(
            pattern, byte_length=options.length, memory_regions=batch
        )

    # The hits are text, so report them as a string of the requested width —
    # a hex dump of a matched URL helps nobody.
    value_type = valuetypes.resolve("string")

    with Timer() as timer:
        outcome = _run_scan(session, search, label="Regex scan")
        state = _store(
            session,
            value_type,
            options.length,
            outcome.addresses,
            f"regex {options.pattern}",
            truncated=outcome.truncated,
        )

    _report(session, state, timer.elapsed, outcome)


def _results_parser() -> CommandParser:
    parser = CommandParser("scan:results")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="print at most N rows, overriding the 'limit' setting",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        metavar="N",
        help="start at row N+1, for paging through a long result set",
    )
    parser.add_argument(
        "--all", action="store_true", help="print every row, ignoring the limit"
    )
    return parser


@command(
    "scan:results",
    parser=_results_parser,
    summary="Show the current result set, re-read.",
    usage="scan:results [--limit N] [--offset N] [--all]",
    details=(
        "Reads every address again, so the VALUE column is what the target "
        "holds now, not what it held when the scan ran. The PREVIOUS column "
        "shows the value the last scan recorded — the one 'scan:next changed' and "
        "friends compare against — and is filled in only where the two "
        "differ.\n\n"
        "Row numbers are what '#N' refers to in an address."
    ),
    examples=("scan:results", "scan:results --all", "scan:results --offset 20 --limit 10"),
)
def cmd_results(session: Session, args: List[str]) -> None:
    options = _results_parser().parse_args(args)

    state = session.require_scan()
    process = session.require_process("scan:results")
    hex_output = bool(session.option("hex"))

    if options.offset < 0:
        raise CommandError("--offset cannot be negative.")

    limit = None if options.all else session.display_limit(options.limit)
    end = len(state.addresses) if limit is None else options.offset + limit
    window = list(range(options.offset, min(end, len(state.addresses))))

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
        total=len(state.addresses),
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
    parser.add_argument("rows", nargs="+", help=_ROWS_HELP)
    return parser


@command(
    "scan:keep",
    parser=_keep_parser,
    summary="Keep only the named result rows.",
    usage="scan:keep <row> [row ...]",
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
    _print_results(session, new_state, limit=None, elapsed=None)


def _drop_parser() -> CommandParser:
    parser = CommandParser("scan:drop")
    parser.add_argument("rows", nargs="+", help=_ROWS_HELP)
    return parser


@command(
    "scan:drop",
    parser=_drop_parser,
    summary="Remove the named result rows.",
    usage="scan:drop <row> [row ...]",
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
    _print_results(session, new_state, limit=None, elapsed=None)


def _reset_parser() -> CommandParser:
    return CommandParser("scan:reset")


@command(
    "scan:reset",
    parser=_reset_parser,
    summary="Discard the current scan results.",
    usage="scan:reset",
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
