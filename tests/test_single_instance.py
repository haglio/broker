"""Tests for the Win32 named-mutex single-instance guards."""
from __future__ import annotations

import uuid

from osr2_broker.single_instance import is_mutex_held, try_acquire_mutex


def test_a_name_nobody_holds_reads_as_free():
    assert not is_mutex_held(f"Local\\osr2-broker-test-{uuid.uuid4().hex}")


def test_a_held_name_reads_as_held():
    name = f"Local\\osr2-broker-test-{uuid.uuid4().hex}"

    handle = try_acquire_mutex(name)
    assert handle is not None
    try:
        assert is_mutex_held(name)
    finally:
        import ctypes

        ctypes.WinDLL("kernel32").CloseHandle(handle)


def test_probing_a_free_name_does_not_claim_it():
    """The probe must not leave a mutex behind — that would lock out the broker."""
    name = f"Local\\osr2-broker-test-{uuid.uuid4().hex}"

    is_mutex_held(name)

    assert try_acquire_mutex(name) is not None
