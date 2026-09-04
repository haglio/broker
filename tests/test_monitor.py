
from osr2_broker.monitor import (
    Action,
    MonitorState,
    load_idle_state,
    read_timestamp,
    run_monitor_poll,
    save_idle_state,
)


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

    def test_sustained_activity_resets_alert(self):
        """Sustained TX (>60s) after acknowledged alert re-arms idle detection."""
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        state.update(now=1998.0, last_rx=1993.0, last_tx=998.0, auto_mode=False)
        state.acknowledge()
        # Sustained TX activity for 70 seconds (polls every 10s)
        for t in range(2000, 2080, 10):
            state.update(now=float(t), last_rx=float(t - 5), last_tx=float(t - 1), auto_mode=False)
        # Activity stops, device idle again
        action = state.update(now=3100.0, last_rx=3095.0, last_tx=2079.0, auto_mode=False)
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

    def test_no_re_alert_after_brief_tx(self):
        """Brief TX (e.g. MFP keepalive) after acknowledged alert must not re-arm."""
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        action = state.update(now=1998.0, last_rx=1993.0, last_tx=998.0, auto_mode=False)
        assert action == Action.IDLE_ALERT
        state.acknowledge()
        # Brief TX blip (single poll with in_use=True)
        state.update(now=2000.0, last_rx=1995.0, last_tx=1999.0, auto_mode=False)
        # TX fades, device idle again
        state.update(now=2040.0, last_rx=2035.0, last_tx=1999.0, auto_mode=False)
        # 15+ min later — should NOT fire a second alert
        action = state.update(now=3000.0, last_rx=2995.0, last_tx=1999.0, auto_mode=False)
        assert action is None

    def test_no_re_alert_after_rx_gap(self):
        """Brief RX gap (device appears off momentarily) must not re-arm alert."""
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        action = state.update(now=1998.0, last_rx=1993.0, last_tx=998.0, auto_mode=False)
        assert action == Action.IDLE_ALERT
        state.acknowledge()
        # RX goes stale — device appears off
        state.update(now=2040.0, last_rx=2000.0, last_tx=998.0, auto_mode=False)
        assert not state.device_on
        # RX resumes — device back on
        state.update(now=2045.0, last_rx=2042.0, last_tx=998.0, auto_mode=False)
        assert state.device_on
        # 15+ min idle — should NOT fire a second alert
        action = state.update(now=3045.0, last_rx=3040.0, last_tx=998.0, auto_mode=False)
        assert action is None

    def test_no_false_alert_when_last_tx_none_on_long_running_device(self):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        state.update(now=1000.0, last_rx=995.0, last_tx=998.0, auto_mode=False)
        state.update(now=2200.0, last_rx=2195.0, last_tx=2198.0, auto_mode=False)
        action = state.update(now=2210.0, last_rx=2205.0, last_tx=None, auto_mode=False)
        assert action is None


class TestRestartPersistence:
    def test_seeded_idle_since_continues_countdown_across_restart(self):
        """A restarted broker must resume the idle countdown from the persisted
        idle_since, not re-anchor it to 'now' (which would reset the 15-min clock)."""
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0, idle_since=1000.0)
        action = state.update(now=1950.0, last_rx=1945.0, last_tx=500.0, auto_mode=False)
        assert action == Action.IDLE_ALERT

    def test_seeded_alerted_suppresses_realert_across_restart(self):
        """If the alert already fired before a restart, seeding alerted=True must
        stop the restarted broker from re-nagging for the same idle episode."""
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0,
                             idle_since=1000.0, alerted=True)
        action = state.update(now=1950.0, last_rx=1945.0, last_tx=500.0, auto_mode=False)
        assert action is None


class TestMonitorPoll:
    def test_poll_persists_state_each_cycle(self, tmp_path):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0)
        idle_file = tmp_path / "idle_state.txt"
        run_monitor_poll(state, now=1000.0, last_rx=995.0, last_tx=998.0,
                         auto_active=False, idle_state_file=idle_file, on_alert=lambda: None)
        assert load_idle_state(idle_file) == (None, False)
        run_monitor_poll(state, now=1500.0, last_rx=1495.0, last_tx=998.0,
                         auto_active=False, idle_state_file=idle_file, on_alert=lambda: None)
        assert load_idle_state(idle_file) == (1000.0, False)

    def test_poll_fires_on_alert_and_persists_alerted(self, tmp_path):
        state = MonitorState(idle_threshold=900.0, rx_stale_threshold=30.0, idle_since=1000.0)
        idle_file = tmp_path / "idle_state.txt"
        calls = []
        run_monitor_poll(state, now=1950.0, last_rx=1945.0, last_tx=500.0,
                         auto_active=False, idle_state_file=idle_file,
                         on_alert=lambda: calls.append(1))
        assert calls == [1]
        assert load_idle_state(idle_file) == (1000.0, True)


class TestIdleStatePersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        p = tmp_path / "idle_state.txt"
        save_idle_state(p, idle_since=1711900000.5, alerted=True)
        assert load_idle_state(p) == (1711900000.5, True)

    def test_save_and_load_none_idle_since(self, tmp_path):
        p = tmp_path / "idle_state.txt"
        save_idle_state(p, idle_since=None, alerted=False)
        assert load_idle_state(p) == (None, False)

    def test_load_missing_returns_defaults(self, tmp_path):
        assert load_idle_state(tmp_path / "nonexistent.txt") == (None, False)

    def test_load_garbage_returns_defaults(self, tmp_path):
        p = tmp_path / "idle_state.txt"
        p.write_text("not json at all")
        assert load_idle_state(p) == (None, False)


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

