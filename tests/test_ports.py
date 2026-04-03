from __future__ import annotations

import logging
import json
from pathlib import Path
from unittest.mock import patch

from osr2_broker.ports import (
    _read_mfp_config_payload,
    collect_com0com_ports,
    ensure_mfp_serial_port,
    read_mfp_selected_serial_port,
    resolve_mfp_serial_port,
    resolve_virtual_port,
)


class TestResolveVirtualPort:
    def test_returns_configured_port_when_present(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")

        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={"COM15": ("com0com - serial port emulator", "COM0COM\\PORT\\CNCB2")},
        ):
            result = resolve_virtual_port(mfp_config, "COM15", logger)

        assert result == "COM15"

    def test_prefers_broker_side_matching_mfp_selection(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")

        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={
                "COM7": ("com0com - serial port emulator CNCA1", "COM0COM\\PORT\\CNCA1"),
                "COM8": ("com0com - serial port emulator CNCB1", "COM0COM\\PORT\\CNCB1"),
            },
        ), patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value="COM0COM\\PORT\\CNCA1"):
            result = resolve_virtual_port(mfp_config, "COM15", logger)

        assert result == "COM8"

    def test_falls_back_to_only_cncb_port(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")

        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={
                "COM7": ("com0com - serial port emulator CNCA1", "COM0COM\\PORT\\CNCA1"),
                "COM8": ("com0com - serial port emulator CNCB1", "COM0COM\\PORT\\CNCB1"),
            },
        ), patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value=None):
            result = resolve_virtual_port(mfp_config, "COM15", logger)

        assert result == "COM8"


class TestResolveMfpSerialPort:
    def test_keeps_selected_port_when_present(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")

        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={
                "COM7": ("com0com - serial port emulator CNCA1", "COM0COM\\PORT\\CNCA1"),
                "COM8": ("com0com - serial port emulator CNCB1", "COM0COM\\PORT\\CNCB1"),
            },
        ), patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value="COM0COM\\PORT\\CNCA1"):
            result = resolve_mfp_serial_port(mfp_config, "COM15", logger)

        assert result == "COM0COM\\PORT\\CNCA1"

    def test_prefers_matching_cnca_side_for_resolved_broker_port(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")

        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={
                "COM7": ("com0com - serial port emulator CNCA1", "COM0COM\\PORT\\CNCA1"),
                "COM8": ("com0com - serial port emulator CNCB1", "COM0COM\\PORT\\CNCB1"),
            },
        ), patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value="COM0COM\\PORT\\CNCA2"):
            result = resolve_mfp_serial_port(mfp_config, "COM15", logger)

        assert result == "COM0COM\\PORT\\CNCA1"

    def test_ensure_mfp_serial_port_updates_config_when_stale(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")
        mfp_config.write_text(
            json.dumps({
                "OutputTarget": {
                    "Items": [{"SelectedSerialPort": "COM0COM\\PORT\\CNCA2"}]
                }
            }),
            encoding="utf-8",
        )

        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={
                "COM7": ("com0com - serial port emulator CNCA1", "COM0COM\\PORT\\CNCA1"),
                "COM8": ("com0com - serial port emulator CNCB1", "COM0COM\\PORT\\CNCB1"),
            },
        ):
            result = ensure_mfp_serial_port(mfp_config, "COM15", logger)

        assert result == "COM0COM\\PORT\\CNCA1"
        payload = json.loads(mfp_config.read_text(encoding="utf-8"))
        assert payload["OutputTarget"]["Items"][0]["SelectedSerialPort"] == "COM0COM\\PORT\\CNCA1"


class TestResolveVirtualPortFallbacks:
    def test_returns_configured_port_when_multiple_cncb_and_no_match(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")
        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={
                "COM7": ("com0com CNCA1", "COM0COM\\PORT\\CNCA1"),
                "COM8": ("com0com CNCB1", "COM0COM\\PORT\\CNCB1"),
                "COM9": ("com0com CNCB2", "COM0COM\\PORT\\CNCB2"),
            },
        ), patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value=None):
            result = resolve_virtual_port(mfp_config, "COM99", logger)
        assert result == "COM99"


class TestResolveMfpSerialPortFallbacks:
    def test_falls_back_to_sole_cnca_port(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")
        with patch(
            "osr2_broker.ports.collect_com0com_ports",
            return_value={
                "COM7": ("com0com CNCA1", "COM0COM\\PORT\\CNCA1"),
                "COM8": ("com0com CNCB1", "COM0COM\\PORT\\CNCB1"),
            },
        ), patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value="STALE_PORT"), \
             patch("osr2_broker.ports.resolve_virtual_port", return_value="COM99"):
            result = resolve_mfp_serial_port(mfp_config, "COM15", logger)
        assert result == "COM0COM\\PORT\\CNCA1"

    def test_returns_selected_port_when_no_com0com_ports(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")
        with patch("osr2_broker.ports.collect_com0com_ports", return_value={}), \
             patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value="COM5"), \
             patch("osr2_broker.ports.resolve_virtual_port", return_value="COM99"):
            result = resolve_mfp_serial_port(mfp_config, "COM15", logger)
        assert result == "COM5"


class TestEnsureMfpSerialPortEdgeCases:
    def test_returns_none_when_resolved_is_none(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")
        with patch("osr2_broker.ports.resolve_mfp_serial_port", return_value=None):
            assert ensure_mfp_serial_port(mfp_config, "COM15", logger) is None

    def test_returns_current_when_already_matches(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        logger = logging.getLogger("test.broker")
        with patch("osr2_broker.ports.resolve_mfp_serial_port", return_value="COM7"), \
             patch("osr2_broker.ports.read_mfp_selected_serial_port", return_value="COM7"):
            result = ensure_mfp_serial_port(mfp_config, "COM15", logger)
        assert result == "COM7"


class TestMfpConfigEdgeCases:
    def test_read_mfp_config_returns_empty_when_file_missing(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        assert _read_mfp_config_payload(mfp_config) == {}

    def test_read_mfp_config_returns_empty_for_invalid_json(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        mfp_config.write_text("NOT JSON", encoding="utf-8")
        assert _read_mfp_config_payload(mfp_config) == {}

    def test_read_mfp_selected_serial_port_returns_none_when_missing(self, tmp_path):
        mfp_config = tmp_path / "MultiFunPlayer.config.json"
        assert read_mfp_selected_serial_port(mfp_config) is None

    def test_collect_com0com_ports_skips_ports_without_device(self, monkeypatch):
        class FakePort:
            device = None
            description = "com0com"
            hwid = "COM0COM\\PORT\\CNCA1"
        monkeypatch.setattr("osr2_broker.ports.iter_serial_ports", lambda: [FakePort()])
        assert collect_com0com_ports() == {}

    def test_collect_com0com_ports_skips_non_com0com_ports(self, monkeypatch):
        class FakePort:
            device = "COM3"
            description = "USB Serial Port"
            hwid = "USB\\VID_1234"
        monkeypatch.setattr("osr2_broker.ports.iter_serial_ports", lambda: [FakePort()])
        assert collect_com0com_ports() == {}

    def test_collect_com0com_ports_collects_matching_ports(self, monkeypatch):
        class FakePort:
            device = "COM7"
            description = "com0com - serial port emulator CNCA1"
            hwid = "COM0COM\\PORT\\CNCA1"
        monkeypatch.setattr("osr2_broker.ports.iter_serial_ports", lambda: [FakePort()])
        result = collect_com0com_ports()
        assert "COM7" in result
