# -*- coding: utf-8 -*-

"""
The state one Picklock session carries.

A shell is only as useful as what it remembers between commands. A session
holds the attached process, the addresses the last scan found (so ``next``
can narrow them and ``#3`` can name one), the paths the last pointer scan
found, the cached region snapshot that keeps an iterative scan from
re-enumerating the address space every time, and the handful of settings
``set`` exposes.

Every command receives the session and touches the target only through it, so
"is a process attached?" and "did that address come from a stale scan?" are
answered in exactly one place.
"""

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyMemoryEditor import (
    AbstractProcess,
    AmbiguousProcessNameError,
    MemoryRegion,
    OpenProcess,
    PointerPath,
    ProcessIDNotExistsError,
    ProcessNotFoundError,
)
from PyMemoryEditor.process.region import default_scan_filter

from . import processes
from .errors import CommandError, NoProcessError
from .output import Printer
from .valuetypes import ValueType


@dataclass(frozen=True)
class Setting:
    """One knob exposed by the ``set`` command."""

    name: str
    default: Any
    kind: type
    summary: str


#: Every session setting, in the order ``set`` prints them.
SETTINGS: Tuple[Setting, ...] = (
    Setting("limit", 20, int, "Rows printed per result table (0 = no limit)."),
    Setting("max_results", 1000000, int, "Scan hits kept in memory (0 = no cap)."),
    Setting("hex", False, bool, "Print integer values in hexadecimal."),
    Setting("timing", True, bool, "Print the elapsed time after each command."),
    Setting("progress", True, bool, "Show a progress line while scanning."),
    Setting("writable_only", False, bool, "Scan only writable regions (faster)."),
    Setting("hex_width", 16, int, "Bytes per line in 'memory:hex' output."),
    Setting("watch_interval", 0.5, float, "Seconds between 'memory:watch' samples."),
)

_SETTINGS_BY_NAME = {setting.name: setting for setting in SETTINGS}


@dataclass
class ScanState:
    """The result set of the last value scan, and what produced it.

    ``values`` runs parallel to ``addresses`` and holds what each address read
    at the moment of the scan — the "previous value" the ``next`` comparisons
    (increased / decreased / changed / unchanged) are defined against.
    """

    value_type: ValueType
    width: int
    addresses: List[int] = field(default_factory=list)
    values: List[Any] = field(default_factory=list)
    description: str = ""
    truncated: bool = False
    #: The scan looked only at writable regions, so nothing in read-only
    #: memory was ever a candidate. Carried on the result set rather than
    #: read from the setting when it is reported, because the setting can be
    #: changed after the scan and the results would then describe themselves
    #: wrongly.
    writable_only: bool = False

    def __len__(self) -> int:
        return len(self.addresses)


class Session:
    """One attached target and everything the shell remembers about it."""

    def __init__(self, printer: Optional[Printer] = None):
        self.printer = printer if printer is not None else Printer()
        self.process: Optional[AbstractProcess] = None
        self.process_name: str = ""
        self.scan: Optional[ScanState] = None
        self.pointer_paths: List[PointerPath] = []
        self.settings: Dict[str, Any] = {
            setting.name: setting.default for setting in SETTINGS
        }
        #: User-defined aliases: the word typed, mapped to the words it stands
        #: for. Kept here rather than in the command registry because they are
        #: the user's, not the program's. A shell loads them from disk at
        #: startup (see picklock.aliases); a Session on its own starts with
        #: none, so nothing built in a test or a script touches a file.
        self.aliases: Dict[str, List[str]] = {}
        self._regions: Optional[List[MemoryRegion]] = None
        self._modules: Optional[Dict[str, int]] = None
        # Set by the shell that owns this session, so 'source' can feed a
        # script file back through the same dispatcher. None when the
        # session is driven programmatically instead of by a shell.
        self.shell: Optional[Any] = None

    # -- settings --------------------------------------------------------

    def option(self, name: str) -> Any:
        """Read a setting by name."""
        return self.settings[name]

    def set_option(self, name: str, text: str) -> Any:
        """Assign a setting from its command-line spelling.

        :raises CommandError: for an unknown name or an unparseable value.
        """
        setting = _SETTINGS_BY_NAME.get(name.strip().lower())
        if setting is None:
            known = ", ".join(item.name for item in SETTINGS)
            raise CommandError(f"Unknown setting {name!r}. Known settings: {known}.")

        raw = text.strip()
        if setting.kind is bool:
            if raw.lower() in ("1", "true", "on", "yes"):
                value: Any = True
            elif raw.lower() in ("0", "false", "off", "no"):
                value = False
            else:
                raise CommandError(f"{setting.name} takes on/off, not {text!r}.")
        elif setting.kind is int:
            try:
                value = int(raw, 0) if raw[:2].lower() == "0x" else int(raw)
            except ValueError:
                raise CommandError(f"{setting.name} takes an integer, not {text!r}.")
            if value < 0:
                raise CommandError(f"{setting.name} cannot be negative.")
        else:
            try:
                value = float(raw)
            except ValueError:
                raise CommandError(f"{setting.name} takes a number, not {text!r}.")
            if value <= 0:
                raise CommandError(f"{setting.name} must be greater than zero.")

        self.settings[setting.name] = value

        # The printer mirrors two settings, because it is what actually prints.
        if setting.name == "timing":
            self.printer.timing = bool(value)
        return value

    def display_limit(self, override: Optional[int] = None) -> Optional[int]:
        """How many rows a table should print: ``None`` means all of them."""
        limit = self.option("limit") if override is None else override
        return None if not limit else int(limit)

    # -- the target ------------------------------------------------------

    @property
    def is_attached(self) -> bool:
        return self.process is not None

    def require_process(self, command: str = "") -> AbstractProcess:
        """Return the attached process or explain that there is not one."""
        if self.process is None:
            raise NoProcessError(command)
        return self.process

    def attach(
        self,
        *,
        pid: Optional[int] = None,
        name: Optional[str] = None,
        case_sensitive: Optional[bool] = None,
        exact_match: bool = True,
        strict_bitness: bool = False,
        permission: Optional[Any] = None,
    ) -> AbstractProcess:
        """Open a target, replacing whatever was attached before.

        Errors PyMemoryEditor raises for a target the user named wrongly
        (no such PID, no such name, an ambiguous name) are re-raised as
        :class:`CommandError` so the shell reports them on one line and stays
        alive; anything else propagates as the bug it probably is.
        """
        kwargs: Dict[str, Any] = {"exact_match": exact_match, "strict_bitness": strict_bitness}
        if pid is not None:
            kwargs["pid"] = pid
        if name is not None:
            kwargs["name"] = name
        # Left unset, each backend keeps its own default (Windows matches names
        # case-insensitively, like the OS; Linux and macOS do not).
        if case_sensitive is not None:
            kwargs["case_sensitive"] = case_sensitive
        if permission is not None:
            kwargs["permission"] = permission

        try:
            process = OpenProcess(**kwargs)
        except (
            ProcessIDNotExistsError,
            ProcessNotFoundError,
            AmbiguousProcessNameError,
        ) as error:
            raise CommandError(str(error))
        except PermissionError as error:
            raise CommandError(
                f"{error} Picklock needs permission to open the target — try "
                "running it as an administrator (Windows), with sudo (Linux), "
                "or with the debugger entitlement (macOS)."
            )
        except OSError as error:
            raise CommandError(f"Could not open the process: {error}")

        self.detach()
        self.process = process
        self.process_name = name or processes.process_name(process.pid) or ""
        return process

    def detach(self) -> bool:
        """Close the attached process and drop everything derived from it."""
        was_attached = self.process is not None
        if self.process is not None:
            try:
                self.process.close()
            except Exception:  # noqa: BLE001 - a dead target cannot be closed
                pass
        self.process = None
        self.process_name = ""
        self.invalidate()
        self.scan = None
        self.pointer_paths = []
        return was_attached

    def invalidate(self) -> None:
        """Drop the cached region snapshot and module table."""
        self._regions = None
        self._modules = None

    # -- cached views of the target --------------------------------------

    def regions(self, *, refresh: bool = False) -> List[MemoryRegion]:
        """The target's memory map, cached for the duration of a workflow.

        A scan re-uses the snapshot instead of re-enumerating the address
        space, which is most of what makes a ``scan`` / ``next`` cycle feel
        immediate. The map does change as the target allocates, so ``refresh``
        (and the ``regions`` command) rebuild it.
        """
        process = self.require_process()
        if self._regions is None or refresh:
            self._regions = list(process.snapshot_memory_regions())
        return self._regions

    def scan_regions(self, *, writable_only: Optional[bool] = None) -> List[MemoryRegion]:
        """The regions a scan will actually walk.

        PyMemoryEditor applies ``default_scan_filter`` internally, so this is
        purely so the progress line counts the same bytes the scan does.
        """
        only_writable = (
            self.option("writable_only") if writable_only is None else writable_only
        )
        return [
            region
            for region in self.regions()
            if default_scan_filter(region, writeable_only=only_writable)
        ]

    def modules(self, *, refresh: bool = False) -> Dict[str, int]:
        """Map lower-cased module name to base address, cached."""
        process = self.require_process()
        if self._modules is None or refresh:
            table: Dict[str, int] = {}
            for module in process.get_modules():
                if module.name:
                    # First entry wins: the loader can map the same name twice
                    # (32/64-bit views on Windows), and the first is the one a
                    # static offset is normally taken against.
                    table.setdefault(module.name.lower(), module.base_address)
            self._modules = table
        return self._modules

    # -- aliases -----------------------------------------------------------

    def expand_alias(self, word: str, args: Sequence[str]) -> Tuple[str, List[str]]:
        """Substitute an alias, returning the command word and its arguments.

        Expanded once, never repeatedly: an alias is checked when it is
        created, so its target is always a real command and a chain cannot
        form. One pass therefore always lands somewhere real, and no depth
        limit or cycle check is needed to promise it.
        """
        tokens = self.aliases.get(word.strip().lower())
        if not tokens:
            return word, list(args)
        return tokens[0], list(tokens[1:]) + list(args)

    # -- hooks used by the address expression parser ----------------------

    def knows_module(self, name: str) -> bool:
        """True when ``name`` resolves to a loaded module.

        Asked by the address parser, which offers it several readings of a
        hyphenated word and keeps the one the target recognises.
        """
        try:
            self.module_base(name)
        except CommandError:
            return False
        return True

    def module_base(self, name: str) -> int:
        """Base address of a loaded module, matched by name then by prefix."""
        self.require_process()
        table = self.modules()
        key = name.lower()

        if key in table:
            return table[key]

        # "game" should find "game.exe" — the extension is noise a user should
        # not have to remember, and an unambiguous prefix is unambiguous.
        matches = [
            module for module in table if module.startswith(key) or key in module
        ]
        if len(matches) == 1:
            return table[matches[0]]
        if len(matches) > 1:
            listed = ", ".join(sorted(matches)[:6])
            raise CommandError(f"Module {name!r} is ambiguous: {listed}.")

        raise CommandError(
            f"No loaded module matches {name!r}. Use 'memory:modules' to list them."
        )

    def read_pointer(self, address: int) -> int:
        """Dereference ``address``, for the ``[...]`` form of an expression."""
        process = self.require_process()
        size = process.pointer_size
        try:
            data = process.read_bytes(address, size)
        except OSError as error:
            raise CommandError(
                f"Cannot read the pointer at 0x{address:X}: {error}"
            )
        return int.from_bytes(data, sys.byteorder)

    def result_address(self, index: int) -> int:
        """The address on row ``index`` (1-based) of the last scan."""
        if self.scan is None or not self.scan.addresses:
            raise CommandError(
                "No scan results to refer to. Run 'scan:value' first, or give an "
                "address instead of a '#' reference."
            )
        if not 1 <= index <= len(self.scan.addresses):
            raise CommandError(
                f"#{index} is out of range — the last scan has "
                f"{len(self.scan.addresses)} result(s)."
            )
        return self.scan.addresses[index - 1]

    # -- scan results -----------------------------------------------------

    def store_scan(
        self,
        value_type: ValueType,
        width: int,
        addresses: Sequence[int],
        values: Sequence[Any],
        description: str,
        *,
        truncated: bool = False,
        writable_only: bool = False,
    ) -> ScanState:
        """Replace the current result set."""
        self.scan = ScanState(
            value_type=value_type,
            width=width,
            addresses=list(addresses),
            values=list(values),
            description=description,
            truncated=truncated,
            writable_only=writable_only,
        )
        return self.scan

    def require_scan(self) -> ScanState:
        """Return the current result set or explain that there is not one."""
        if self.scan is None or not self.scan.addresses:
            raise CommandError('No scan results. Run "scan:value <type> <value>" first.')
        return self.scan

    def close(self) -> None:
        """Release the target. Safe to call more than once."""
        self.detach()


__all__ = ("SETTINGS", "ScanState", "Session", "Setting")
