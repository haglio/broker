from __future__ import annotations

from osr2_broker.single_instance import MUTEX_BROKER, MUTEX_IDLE_WARNING, MUTEX_TRAY


def test_the_names_stay_as_they_are_so_a_broker_from_before_a_change_still_refuses_a_second():
    assert (MUTEX_BROKER, MUTEX_TRAY, MUTEX_IDLE_WARNING) == (
        "Global\\OSR2Broker", "Global\\OSR2Broker.Tray", "Global\\OSR2Broker.IdleWarning")
