from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_broker_tray_uses_single_dynamic_start_restart_action():
    text = _read("scripts/broker_tray.ps1")

    assert "$actionItem = $menu.Items.Add('Start broker')" in text
    assert "Restart broker" in text
    assert "$pauseItem = $menu.Items.Add('Pause broker')" in text
    assert "$startItem" not in text
    assert "$restartItem" not in text


def test_broker_tray_shows_status_as_disabled_menu_text():
    text = _read("scripts/broker_tray.ps1")

    assert "$statusItem = $menu.Items.Add('Broker status: unknown')" in text
    assert "$statusItem.Enabled = $false" in text
    assert "Status refresh" not in text
    assert "$quitItem = $menu.Items.Add('Quit')" in text
    assert "Close tray icon" not in text


def test_broker_tray_uses_fun_time_icon_when_available():
    text = _read("scripts/broker_tray.ps1")

    assert "$trayIconPath = Join-Path $projectRoot 'broker_icon.ico'" in text
    assert "$trayIcon = New-Object System.Drawing.Icon($trayIconPath)" in text
    assert "$notifyIcon.Icon = $trayIcon" in text
    assert "$script:trayIcon = $trayIcon" in text


def test_broker_tray_keeps_custom_icon_during_status_updates():
    text = _read("scripts/broker_tray.ps1")

    update_start = text.index("function Update-NotifyIcon {")
    enable_styles = text.index("[System.Windows.Forms.Application]::EnableVisualStyles()", update_start)
    update_block = text[update_start:enable_styles]

    assert "if ($script:trayIcon -ne $null)" in update_block
    assert "$script:notifyIcon.Icon = $script:trayIcon" in update_block


def test_broker_tray_quit_stops_broker_and_tray():
    text = _read("scripts/broker_tray.ps1")

    assert "$quitItem.add_Click({" in text
    assert "Stop-BrokerProcess" in text


def test_broker_tray_pause_keeps_tray_alive():
    text = _read("scripts/broker_tray.ps1")

    pause_start = text.index("$pauseItem.add_Click({")
    log_start = text.index("$logItem = $menu.Items.Add('Open broker log')", pause_start)
    pause_block = text[pause_start:log_start]

    assert "Stop-BrokerProcess" in pause_block
    assert "[System.Windows.Forms.Application]::Exit()" not in pause_block
