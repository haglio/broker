"""The verb channel fun_time, genau and clipper steer the broker through.

The consumer is the family's (``app_support.file_channel``, tested there): every
queued verb, folded to upper case, the queue claimed by rename so a verb written
into the drain is never erased unread.  What is the broker's is that a verb
dropped in the file reaches the session once, and that a read which cannot make
sense of the file never raises into the loop.
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

from app_support.file_channel import consume_command_file

from osr2_broker.activity import ActivityStamp


def test_an_undecodable_file_reads_as_no_command(tmp_path: Path):
    """A half-written or foreign-encoded file must never raise into the loop."""
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_bytes(b"\xff\xfe\x00park")

    assert consume_command_file(cmd) == []


def test_an_unreadable_path_logs_and_reads_as_no_command(tmp_path: Path):
    logger = MagicMock()

    # A directory exists but cannot be claimed and read as text, on any platform.
    assert consume_command_file(tmp_path, logger=logger) == []
    logger.exception.assert_called_once()


def test_a_park_written_to_the_file_schedules_the_hold_exactly_once(tmp_path: Path):
    """The whole channel, end to end: a lower-case 'park' dropped in the file is
    consumed on the next tick and scheduled once — the claim takes the queue
    away, so the ticks after it see nothing, and the hold's clock is never
    pushed back."""
    from osr2_broker.session import BrokerSerialSession

    clock = [10.0]
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("park", encoding="utf-8")

    auto_mode = MagicMock()
    auto_mode.is_active = False
    auto_mode.consume_deactivation.return_value = False
    logger = MagicMock()
    session = BrokerSerialSession(
        serial_factory=MagicMock(),
        virtual_port="COM15",
        real_port="COM4",
        baud=115200,
        broker_cmd_file=cmd,
        genau_enabled_file=tmp_path / "genau_enabled.txt",
        auto_stale_timeout=2.0,
        stop_event=threading.Event(),
        broker_paused=threading.Event(),
        auto_mode=auto_mode,
        logger=logger,
        start_thread=MagicMock(),
        consume_command=consume_command_file,
        read_genau_enabled=lambda _path: True,
        rx_activity=ActivityStamp(tmp_path / "osr2_serial_rx.txt"),
        tx_activity=ActivityStamp(tmp_path / "osr2_serial_tx.txt"),
        connected_event=threading.Event(),
        is_retryable_error=lambda _exc: False,
        monotonic=lambda: clock[0],
    )
    real_port = MagicMock()
    lock = threading.Lock()

    session.tick_command_and_stale_timeout(object(), real_port=real_port, serial_write_lock=lock)
    clock[0] = 10.5
    session.tick_command_and_stale_timeout(object(), real_port=real_port, serial_write_lock=lock)

    # 11.2 is past the first tick's schedule (11.0) but short of where a replay
    # on the second tick would have pushed it (11.5): a replayed verb means no
    # write lands here.
    clock[0] = 11.2
    session.tick_command_and_stale_timeout(object(), real_port=real_port, serial_write_lock=lock)

    real_port.write.assert_called_once_with(b"L00000I500\n")
    scheduled = [c.args[0] for c in logger.info.call_args_list]
    assert scheduled.count("OmniPause: park scheduled") == 1


def test_two_verbs_queued_between_ticks_are_both_acted_on_in_order(tmp_path: Path):
    """The defect the broker's own consumer had: two verbs read together came
    back as one word matching neither, and a verb written into the truncate
    was erased unread.  A park then a resume now parks and then resumes."""
    from osr2_broker.session import BrokerSerialSession

    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("park\nresume\n", encoding="utf-8")
    auto_mode = MagicMock()
    auto_mode.is_active = False
    auto_mode.consume_deactivation.return_value = False
    logger = MagicMock()
    session = BrokerSerialSession(
        serial_factory=MagicMock(), virtual_port="COM15", real_port="COM4", baud=115200,
        broker_cmd_file=cmd, genau_enabled_file=tmp_path / "genau_enabled.txt",
        auto_stale_timeout=2.0, stop_event=threading.Event(), broker_paused=threading.Event(),
        auto_mode=auto_mode, logger=logger, start_thread=MagicMock(),
        consume_command=consume_command_file, read_genau_enabled=lambda _path: True,
        rx_activity=ActivityStamp(tmp_path / "osr2_serial_rx.txt"),
        tx_activity=ActivityStamp(tmp_path / "osr2_serial_tx.txt"),
        connected_event=threading.Event(), is_retryable_error=lambda _exc: False,
        monotonic=lambda: 10.0,
    )

    session.tick_command_and_stale_timeout(
        object(), real_port=MagicMock(), serial_write_lock=threading.Lock())

    said = [c.args[0] for c in logger.info.call_args_list]
    assert said.index("OmniPause: park scheduled") < said.index("OmniPause: broker resumed")
