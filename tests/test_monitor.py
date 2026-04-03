from pathlib import Path

from osr2_broker.monitor import Action, MonitorState, read_timestamp, read_auto_mode


class TestDeviceOff:
    def test_no_action_when_no_rx_data(self):
        state = MonitorState()
        action = state.update(now=1000.0, last_rx=None, last_tx=None, auto_mode=False)
        assert action is None
        assert not state.device_on

    def test_device_off_when_rx_stale(self):
        state = MonitorState(rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=960.0, last_tx=None, auto_mode=False)
        assert not state.device_on


class TestDeviceOn:
    def test_device_on_when_rx_fresh(self):
        state = MonitorState(rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=990.0, last_tx=None, auto_mode=False)
        assert state.device_on

    def test_no_alert_when_device_in_use_via_tx(self):
        state = MonitorState(idle_threshold=900.0)
        action = state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        assert action is None

    def test_no_alert_when_device_in_use_via_auto_mode(self):
        state = MonitorState(idle_threshold=900.0)
        action = state.update(now=1000.0, last_rx=995.0, last_tx=None, auto_mode=True)
        assert action is None


class TestIdleAlert:
    def test_alert_after_idle_threshold(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        action = state.update(now=1998.0, last_rx=1993.0, last_tx=998.0, auto_mode=False)
        assert action == Action.IDLE_ALERT

    def test_no_re_alert_after_first(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        action = state.update(now=1998.0, last_rx=1993.0, last_tx=998.0, auto_mode=False)
        assert action == Action.IDLE_ALERT
        action = state.update(now=2050.0, last_rx=2045.0, last_tx=998.0, auto_mode=False)
        assert action is None

    def test_new_activity_resets_alert(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        state.update(now=1998.0, last_rx=1993.0, last_tx=998.0, auto_mode=False)
        state.acknowledge()
        state.update(now=2000.0, last_rx=1995.0, last_tx=1999.0, auto_mode=False)
        action = state.update(now=3000.0, last_rx=2995.0, last_tx=1999.0, auto_mode=False)
        assert action == Action.IDLE_ALERT

    def test_backdate_to_last_tx_when_recent(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=995.0, auto_mode=False)
        action = state.update(now=1200.0, last_rx=1195.0, last_tx=1100.0, auto_mode=False)
        assert action is None
        action = state.update(now=2000.0, last_rx=1995.0, last_tx=1100.0, auto_mode=False)
        assert action == Action.IDLE_ALERT

    def test_device_off_clears_idle_state(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        state.update(now=1500.0, last_rx=1495.0, last_tx=998.0, auto_mode=False)
        state.update(now=1600.0, last_rx=None, last_tx=998.0, auto_mode=False)
        assert not state.device_on
        state.update(now=1700.0, last_rx=1695.0, last_tx=998.0, auto_mode=False)
        action = state.update(now=1800.0, last_rx=1795.0, last_tx=998.0, auto_mode=False)
        assert action is None

    def test_no_alert_before_threshold(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        action = state.update(now=1840.0, last_rx=1835.0, last_tx=998.0, auto_mode=False)
        assert action is None

    def test_no_alert_while_warning_pending(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        action = state.update(now=1998.0, last_rx=1993.0, last_tx=998.0, auto_mode=False)
        assert action == Action.IDLE_ALERT
        state.update(now=2000.0, last_rx=1995.0, last_tx=1999.0, auto_mode=False)
        action = state.update(now=3000.0, last_rx=2995.0, last_tx=1999.0, auto_mode=False)
        assert action is None

    def test_no_false_alert_when_last_tx_none_on_long_running_device(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        state.update(now=2200.0, last_rx=2195.0, last_tx=2198.0, auto_mode=False)
        action = state.update(now=2210.0, last_rx=2205.0, last_tx=None, auto_mode=False)
        assert action is None


class TestFileReaders:
    def test_read_timestamp_valid(self, tmp_path):
        f = tmp_path / "ts.txt"
        f.write_text("1711900000.123")
        assert read_timestamp(f) == 1711900000.123

    def test_read_timestamp_missing(self, tmp_path):
        assert read_timestamp(tmp_path / "nonexistent.txt") is None

    def test_read_timestamp_garbage(self, tmp_path):
        f = tmp_path / "ts.txt"
        f.write_text("not a number")
        assert read_timestamp(f) is None

    def test_read_auto_mode_active(self, tmp_path):
        f = tmp_path / "mode.txt"
        f.write_text("1")
        assert read_auto_mode(f) is True

    def test_read_auto_mode_inactive(self, tmp_path):
        f = tmp_path / "mode.txt"
        f.write_text("0")
        assert read_auto_mode(f) is False

    def test_read_auto_mode_missing(self, tmp_path):
        assert read_auto_mode(tmp_path / "nonexistent.txt") is False
