# -*- coding: utf-8 -*-

"""The scan runner: batching, caps, interruption and unreadable regions.

These exercise ``_run_scan`` directly with a stand-in search callable, so the
partial-result rules are covered without attaching to a process.
"""

import pytest

from PyMemoryEditor import MemoryRegion

from picklock.commands.scan_commands import _BATCH_BYTES, _batch_regions, _run_scan
from picklock.session import Session


def make_regions(count: int, size: int = _BATCH_BYTES):
    return [
        MemoryRegion(address=(index + 1) * size, size=size, is_readable=True)
        for index in range(count)
    ]


@pytest.fixture
def scannable(session: Session, monkeypatch):
    """A session whose scan regions are three separate batches."""
    regions = make_regions(3)
    monkeypatch.setattr(session, "scan_regions", lambda **kwargs: regions)
    monkeypatch.setattr(session, "regions", lambda **kwargs: regions)
    return session


def test_regions_are_batched_by_byte_budget():
    batches = list(_batch_regions(make_regions(3)))
    assert len(batches) == 3
    small = list(_batch_regions(make_regions(4, size=16), budget=64))
    assert [len(batch) for batch, _ in small] == [4]


def test_every_batch_is_searched(scannable):
    seen = []

    def search(batch):
        seen.append(batch[0].address)
        return iter(())

    outcome = _run_scan(scannable, search)
    assert len(seen) == 3
    assert outcome.addresses == []
    assert outcome.skipped == 0


def test_an_unreadable_batch_is_skipped_not_fatal(scannable):
    """One page the target will not hand over must not lose the whole scan.

    This is the macOS 'mach_vm_read_overwrite failed: (os/kern) memory error'
    case: a file-backed page whose pager declines to produce data, sitting in
    the middle of an address space that is otherwise perfectly readable.
    """
    calls = []

    def search(batch):
        calls.append(batch)
        if len(calls) == 2:
            raise OSError("mach_vm_read_overwrite failed: (os/kern) memory error")
        yield batch[0].address + 8

    outcome = _run_scan(scannable, search)

    assert len(calls) == 3, "the scan must carry on past the failing batch"
    assert outcome.skipped == 1
    assert outcome.last_error is not None
    assert len(outcome.addresses) == 2, "the readable batches still contribute"


def test_results_found_before_a_failure_are_kept(scannable):
    def search(batch):
        yield batch[0].address
        raise OSError("page vanished mid-batch")

    outcome = _run_scan(scannable, search)
    assert len(outcome.addresses) == 3
    assert outcome.skipped == 3


def test_interrupting_keeps_what_was_found(scannable):
    calls = []

    def search(batch):
        calls.append(batch)
        if len(calls) == 3:
            raise KeyboardInterrupt
        yield batch[0].address

    outcome = _run_scan(scannable, search)
    assert outcome.interrupted is True
    assert len(outcome.addresses) == 2


def test_the_max_results_cap_stops_the_scan(scannable):
    scannable.set_option("max_results", "2")
    calls = []

    def search(batch):
        calls.append(batch)
        yield batch[0].address
        yield batch[0].address + 4
        yield batch[0].address + 8

    outcome = _run_scan(scannable, search)
    assert outcome.truncated is True
    assert len(outcome.addresses) == 2
    assert len(calls) == 1, "the cap must stop the scan, not just trim the output"


def test_a_cap_of_zero_means_no_cap(scannable):
    scannable.set_option("max_results", "0")

    def search(batch):
        yield batch[0].address

    outcome = _run_scan(scannable, search)
    assert outcome.truncated is False
    assert len(outcome.addresses) == 3
